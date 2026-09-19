"""Local execution audit. No network exporter; records are scoped to callers."""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import time
from uuid import uuid4

from fastapi import HTTPException, Query, Request
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider, SpanProcessor
from agentscope.middleware import TracingMiddleware
from agentscope.message import Msg

log = logging.getLogger(__name__)
CURRENT = ContextVar('execution_audit', default=None)
MAX_TEXT = 20000


def clean(value, depth=0):
    """Bound payloads and redact conventional credential fields before storage."""
    if depth > 12:
        return '[内容层级过深]'
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    if isinstance(value, dict):
        return {str(k): '[已隐藏]' if re.search(r'password|secret|api.?key|authorization|access.?token|cookie', str(k), re.I)
                else clean(v, depth + 1) for k, v in list(value.items())[:100]}
    if isinstance(value, (list, tuple)):
        return [clean(v, depth + 1) for v in value[:100]]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, (dict, list)):
                return clean(parsed, depth + 1)
        except (ValueError, TypeError):
            pass
        value = re.sub(r'(?i)(bearer\s+)[\w.\-/+=]+', r'\1[已隐藏]', value)
        value = re.sub(r'(?i)((?:api[_-]?key|password|secret|access_token)\s*[=:]\s*)[^\s&,;]+', r'\1[已隐藏]', value)
        return value[:MAX_TEXT] + ('\n[内容已截断]' if len(value) > MAX_TEXT else '')
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return clean(str(value), depth + 1)


def text_content(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join(filter(None, (text_content(v) for v in value)))
    if isinstance(value, dict):
        return str(value.get('text', '')) or text_content(value.get('content', value.get('parts', [])))
    return ''


class AuditStore:
    def __init__(self, path):
        self.path = Path(path)
        self.write_lock = asyncio.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, user_id TEXT, project_id TEXT,
                    agent_id TEXT, session_id TEXT, started REAL, source TEXT,
                    status TEXT, payload TEXT);
                CREATE INDEX IF NOT EXISTS audit_project ON runs(project_id, started);
                CREATE INDEX IF NOT EXISTS audit_session ON runs(user_id, agent_id, session_id, started);
            ''')
        os.chmod(self.path, 0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=3)

    async def persist(self, row):
        async with self.write_lock:
            snapshot = json.loads(json.dumps({k: v for k, v in row.items() if not k.startswith('_')}, ensure_ascii=False))
            await asyncio.to_thread(self.save, snapshot)

    def save(self, row):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?)', (
                row['id'], row['user_id'], row.get('project_id'), row['agent_id'],
                row['session_id'], row['started'], row['source'], row['status'],
                json.dumps(row, ensure_ascii=False)))
            db.execute('DELETE FROM runs WHERE started < ?', (time.time() - 30 * 86400,))

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM runs WHERE id=?', (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def query(self, filters, limit=30, before=None, since=None):
        clauses, args = [], []
        for key, value in filters.items():
            if key not in {'project_id', 'user_id', 'agent_id', 'session_id', 'source', 'status'}:
                raise ValueError(key)
            if value is None:
                clauses.append(key + ' IS NULL')
            else:
                clauses.append(key + '=?'); args.append(value)
        if since is not None:
            clauses.append('started >= ?'); args.append(since)
        if before is not None:
            clauses.append('started < ?'); args.append(before)
        with self.connect() as db:
            rows = db.execute('SELECT payload FROM runs WHERE ' + (' AND '.join(clauses) or '1') +
                              ' ORDER BY started DESC LIMIT ?', [*args, limit + 1]).fetchall()
        return [json.loads(r[0]) for r in rows[:limit]], len(rows) > limit


class LocalSpanProcessor(SpanProcessor):
    def on_end(self, span):
        row = CURRENT.get()
        if row is None:
            return
        try:
            attrs = dict(span.attributes or {})
            if attrs.get('gen_ai.operation.name') == 'chat':
                for label in ('input', 'output'):
                    count = attrs.get(f'gen_ai.usage.{label}_tokens')
                    if count is not None:
                        row[label + '_tokens'] = (row[label + '_tokens'] or 0) + count
            if attrs.get('gen_ai.operation.name') == 'execute_tool':
                row['tool_count'] += 1
            result = clean(attrs.get('gen_ai.tool.call.result'))
            tool_failed = isinstance(result, dict) and result.get('state') in ('error', 'denied')
            if tool_failed:
                row['tool_errors'] += 1
            if len(row['spans']) >= 500:
                row['truncated'] = True
                return
            row['spans'].append({
                'id': format(span.context.span_id, '016x'),
                'parent_id': format(span.parent.span_id, '016x') if span.parent else None,
                'name': span.name, 'started': span.start_time / 1e9,
                'duration_ms': (span.end_time - span.start_time) / 1e6,
                'status': 'ERROR' if tool_failed else span.status.status_code.name,
                'attributes': clean(attrs),
                'events': clean([{'name': e.name, 'attributes': dict(e.attributes or {})} for e in span.events]),
            })
            if row.get('_closed'):
                async def persist_late_span():
                    try:
                        await row['_store'].persist(row)
                    except Exception:
                        log.exception('Unable to persist background tool audit')
                asyncio.get_running_loop().create_task(persist_late_span())
        except Exception:
            log.exception('Unable to collect audit span')


class AuditMiddleware(TracingMiddleware):
    async def on_reply(self, agent, input_kwargs, next_handler):
        row = CURRENT.get()
        gen = super().on_reply(agent, input_kwargs, next_handler)
        try:
            async for event in gen:
                if row is not None:
                    try:
                        self.capture(row, event)
                    except Exception:
                        log.exception('Unable to collect audit event')
                yield event
        finally:
            await gen.aclose()

    @staticmethod
    def capture(row, event):
        data = event.model_dump(mode='json')
        reply_id = data.get('reply_id')
        if reply_id and reply_id not in row['reply_ids']:
            row['reply_ids'].append(reply_id)
        if isinstance(event, Msg):
            row['output'] = clean(event.get_text_content() or '')
            if event.id not in row['reply_ids']:
                row['reply_ids'].append(event.id)
        reason = data.get('finished_reason')
        if reason:
            row['status'] = {'error': 'error', 'interrupted': 'cancelled',
                             'exceed_max_iters': 'limited',
                             'require_user_confirm': 'waiting', 'require_external_execution': 'waiting'}.get(reason, 'completed')
        if data.get('error'):
            row['error'] = clean(data['error'])
            row['status'] = 'error'
        # Inbox hints carry actual channel sender / schedule source; session
        # origin alone only describes who originally opened the session.
        if 'hint' in str(data.get('type', '')).lower():
            row['triggers'] = (row['triggers'] + [clean(data)])[-50:]
            src = clean(data.get('source'))
            if isinstance(src, dict) and src.get('label') in ('schedule', 'channel'):
                row['source'] = src['label']
            if not row['input']:
                row['input'] = text_content(clean(data.get('hint')))



class AuditObserver:
    def __init__(self, store, storage):
        self.store, self.storage = store, storage

    def error(self, error, reply_id=None):
        row = CURRENT.get()
        if row is not None:
            row['status'] = 'error'
            row['error'] = clean(str(error))
            if reply_id and reply_id not in row['reply_ids']:
                row['reply_ids'].append(reply_id)

    @asynccontextmanager
    async def run(self, user_id, session_id, agent_id, input_msg):
        row = {'id': uuid4().hex, 'user_id': user_id, 'agent_id': agent_id,
               'session_id': session_id, 'project_id': None, 'started': time.time(),
               'source': 'web' if isinstance(input_msg, (Msg, list)) else 'background',
               'status': 'running', 'input': text_content(clean(input_msg)), 'output': '',
               'input_tokens': None, 'output_tokens': None, 'tool_count': 0, 'tool_errors': 0,
               'reply_ids': [], 'spans': [], 'triggers': []}
        messages = input_msg if isinstance(input_msg, list) else [input_msg]
        row['senders'] = list(dict.fromkeys(m.name for m in messages if isinstance(m, Msg)))
        try:
            from portal import load
            from project_files import member_key
            row['project_id'] = load().get('project_sessions', {}).get(member_key(user_id, agent_id, session_id))
            session = await self.storage.get_session(user_id, agent_id, session_id)
            if session:
                row['session_name'] = session.config.name
                row['origin'] = clean(session.origin)
                origin_type = getattr(session.origin, 'type', 'user')
                if origin_type != 'user':
                    row['source'] = origin_type
            await self.store.persist(row)
        except Exception:
            log.exception('Unable to initialize audit record; chat continues')
        token = CURRENT.set(row)
        row['_store'] = self.store
        try:
            with trace.get_tracer('agentscope.local_audit').start_as_current_span('chat.run') as span:
                row['trace_id'] = format(span.get_span_context().trace_id, '032x')
                try:
                    yield
                except asyncio.CancelledError:
                    row['status'] = 'cancelled'
                    raise
                except BaseException as exc:
                    self.error(exc)
                    raise
        finally:
            CURRENT.reset(token)
            if row['status'] == 'running':
                row['status'] = 'completed'
            row['duration_ms'] = (time.time() - row['started']) * 1000
            row['spans'].sort(key=lambda s: s['started'])
            # Native agent spans also expose final messages and paused tools.
            for s in row['spans']:
                a = s['attributes']
                if a.get('gen_ai.operation.name') == 'invoke_agent':
                    row['output'] = text_content(a.get('gen_ai.output.messages')) or row['output']
                    rid = a.get('agentscope.agent.reply_id')
                    if rid and rid not in row['reply_ids']:
                        row['reply_ids'].append(rid)
                    if row['status'] == 'completed' and (a.get('agentscope.agent.hitl_pending_tools') or a.get('agentscope.agent.external_execution_pending_tools')):
                        row['status'] = 'waiting'
            row['_closed'] = True
            task = asyncio.create_task(self.store.persist(row))
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise
            except Exception:
                log.exception('Unable to save audit record; chat continues')


def summary(row):
    return {k: v for k, v in row.items() if k not in ('spans', 'triggers', 'origin')} | {
        'input': row['input'][:180], 'output': row['output'][:180]}


def install_routes(router, app):
    store = app.state.audit_observer.store
    from audit_csv import install_routes as install_csv_routes
    install_csv_routes(router, app)

    def caller(request):
        from portal import user_for
        user = request.headers.get('x-user-id', '')
        user_for(user)
        return user

    def project_access(user, pid):
        from portal import ADMIN, load
        from project_files import accessible
        if user == ADMIN:
            p = load().get('projects', {}).get(pid)
            if not p or p.get('deleted'):
                raise HTTPException(404, '项目不存在')
        else:
            accessible(user, pid)

    async def authorize(user, row):
        from portal import ADMIN
        if user == ADMIN:
            return
        if row.get('project_id'):
            project_access(user, row['project_id'])
        if row['user_id'] != user and user != ADMIN:
            raise HTTPException(404, '执行记录不存在')
        if row['user_id'] == user and not row.get('project_id'):
            session = await app.state.storage.get_session(user, row['agent_id'], row['session_id'])
            if session is None:
                raise HTTPException(404, '会话不存在')

    def admin(request):
        from portal import ADMIN
        if caller(request) != ADMIN:
            raise HTTPException(403, '仅管理员可查看全站审计')

    @router.get('/audit/options')
    async def audit_options(request: Request):
        from portal import load
        admin(request)
        def read_options():
            with store.connect() as db:
                users = [r[0] for r in db.execute('SELECT DISTINCT user_id FROM runs ORDER BY user_id')]
                projects = [r[0] for r in db.execute('SELECT DISTINCT project_id FROM runs WHERE project_id IS NOT NULL ORDER BY project_id')]
            return users, projects
        users, projects = await asyncio.to_thread(read_options)
        names = load().get('projects', {})
        return {'users': users, 'projects': [{'id': pid, 'name': names.get(pid, {}).get('name', pid) + ('（已删除）' if names.get(pid, {}).get('deleted') else '')} for pid in projects]}

    @router.get('/audit/runs')
    async def global_runs(request: Request, user_id: str = '', project_id: str = '',
                          source: str = '', status: str = '', days: int = Query(30, ge=1, le=30),
                          before: float | None = None, limit: int = Query(30, ge=1, le=100)):
        from portal import load
        admin(request)
        filters = {}
        if user_id: filters['user_id'] = user_id
        if project_id: filters['project_id'] = None if project_id == '__ordinary__' else project_id
        if source: filters['source'] = source
        if status: filters['status'] = status
        rows, more = await asyncio.to_thread(store.query, filters, limit, before, time.time() - days * 86400)
        projects = load().get('projects', {})
        items = [summary(row) | {'project_name': projects.get(row.get('project_id'), {}).get('name', row.get('project_id') or '普通会话')} for row in rows]
        return {'items': items, 'has_more': more, 'next_before': rows[-1]['started'] if more else None}

    @router.get('/projects/{pid}/audit')
    async def project_runs(pid: str, request: Request, source: str = '', status: str = '',
                           before: float | None = None, limit: int = Query(30, ge=1, le=100)):
        from portal import ADMIN
        user = caller(request); project_access(user, pid)
        filters = {'project_id': pid}
        if user != ADMIN:
            filters['user_id'] = user
        if source: filters['source'] = source
        if status: filters['status'] = status
        rows, more = await asyncio.to_thread(store.query, filters, limit, before)
        return {'items': [summary(r) for r in rows], 'has_more': more,
                'next_before': rows[-1]['started'] if more else None}

    @router.get('/audit/runs/{run_id}')
    async def run_detail(run_id: str, request: Request):
        user = caller(request)
        row = await asyncio.to_thread(store.get, run_id)
        if not row: raise HTTPException(404, '执行记录不存在')
        await authorize(user, row)
        return row

    @router.get('/audit/sessions/{agent_id}/{session_id}/replies/{reply_id}')
    async def reply_detail(agent_id: str, session_id: str, reply_id: str, request: Request):
        user = caller(request)
        session = await app.state.storage.get_session(user, agent_id, session_id)
        if session is None: raise HTTPException(404, '会话不存在')
        rows, _ = await asyncio.to_thread(store.query, {'user_id': user, 'agent_id': agent_id, 'session_id': session_id}, 10000)
        matches = [r for r in rows if reply_id in r['reply_ids']]
        for row in matches: await authorize(user, row)
        return {'items': sorted(matches, key=lambda r: r['started'])}


def install_audit(app):
    from data_paths import DATA_ROOT
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    if not getattr(provider, '_local_audit_installed', False):
        provider.add_span_processor(LocalSpanProcessor())
        provider._local_audit_installed = True
    app.state.audit_observer = AuditObserver(AuditStore(DATA_ROOT / 'audit' / 'executions.sqlite3'), app.state.storage)
