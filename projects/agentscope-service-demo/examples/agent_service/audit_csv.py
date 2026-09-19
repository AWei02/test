"""CSV exports of stored conversations and time-filtered audit question/answers."""
import asyncio
import csv
from datetime import datetime, timezone
import io
import json
import time
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Query, Request
from fastapi.responses import Response

HEADERS = ['执行时间', '用户', '来源', '项目名称', '会话名称', '会话 ID',
           '用户问题', 'AI 回答', '模型名称', '输入 Token', '输出 Token', '执行状态', '错误信息']
SOURCES = {'web': 'Web 对话', 'user': 'Web 对话', 'channel': '渠道', 'schedule': '定时任务',
           'background': '后台唤醒', 'team': '子智能体'}
STATES = {'completed': '完成', 'error': '失败', 'cancelled': '已取消', 'interrupted': '已取消',
          'running': '执行中', 'waiting': '等待确认 / 外部结果', 'limited': '达到迭代上限', 'exceed_max_iters': '达到迭代上限'}


def obj(value):
    return value.model_dump(mode='json') if hasattr(value, 'model_dump') else value


def plain(message):
    """Only visible text blocks: no reasoning, prompts, tool payloads or JSON."""
    content = message.get('content', [])
    if isinstance(content, str):
        return content
    return '\n'.join(b.get('text', '') for b in content if b.get('type') == 'text')


def pairs(messages):
    pending, result = [], []
    for message in messages:
        if message.get('role') == 'user':
            pending.append(message)
        elif message.get('role') == 'assistant':
            result.append((pending, message))
            pending = []
    if pending:
        result.append((pending, {}))
    return result


async def history(storage, user, session):
    pages, before, seen = [], None, set()
    while True:
        page, more = await storage.list_messages(user, session, limit=200, before=before)
        page = [obj(m) for m in page]
        if not page:
            if more: raise HTTPException(409, '会话记录正在变化，请稍后重新导出')
            break
        pages.append(page)
        if not more: break
        before = page[0]['id']
        if before in seen: raise HTTPException(409, '会话分页未推进，请重新导出')
        seen.add(before)
    return [m for page in reversed(pages) for m in page]


def beijing(value):
    if not value: return ''
    if isinstance(value, (float, int)):
        dt = datetime.fromtimestamp(value, timezone.utc)
    else:
        try: dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError: return str(value)
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')


def cell(value):
    value = '' if value is None else str(value)
    # Prevent spreadsheet formula evaluation while preserving multiline text.
    if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r')):
        value = "'" + value
    return value


def response(rows, filename):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(HEADERS)
    writer.writerows([[cell(v) for v in row] for row in rows])
    return Response(output.getvalue().encode('utf-8-sig'), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"', 'Cache-Control': 'no-store'})


def models(runs):
    return ' / '.join(dict.fromkeys(str(s['attributes']['gen_ai.request.model']) for r in runs
        for s in r.get('spans', []) if s.get('attributes', {}).get('gen_ai.operation.name') == 'chat'
        and s['attributes'].get('gen_ai.request.model')))


def row_for(user, session_id, name, project, source, question, answer, timestamp, runs, message=None):
    message = message or {}
    usage = message.get('usage') or {}
    def tokens(key):
        if usage.get(key) is not None: return usage[key]
        counts = [r[key] for r in runs if r.get(key) is not None]
        return sum(counts) if counts else ''
    latest = runs[-1] if runs else {}
    error = message.get('error') or latest.get('error') or ''
    if isinstance(error, dict): error = error.get('message', '')
    status = message.get('finished_reason') or latest.get('status', '')
    return [beijing(timestamp), user, SOURCES.get(source, source), project, name, session_id,
            question, answer, models(runs), tokens('input_tokens'), tokens('output_tokens'),
            STATES.get(status, status), error]


def audit_rows(store, filters):
    allowed = {'user_id', 'project_id', 'source', 'status', 'session_id', 'agent_id'}
    where, args = [], []
    for key, value in filters.items():
        if key not in allowed: raise ValueError(key)
        if value is None: where.append(key + ' IS NULL')
        else: where.append(key + '=?'); args.append(value)
    with store.connect() as db:
        return [json.loads(r[0]) for r in db.execute('SELECT payload FROM runs WHERE ' +
                (' AND '.join(where) or '1') + ' ORDER BY started, id', args)]


def install_routes(router, app):
    store, storage = app.state.audit_observer.store, app.state.storage

    def caller(request):
        from portal import user_for
        user = request.headers.get('x-user-id', '')
        user_for(user)
        return user

    async def session_export(user, agent_id, session_id, viewer=None):
        from portal import ADMIN, load
        from project_files import member_key, accessible
        session = await storage.get_session(user, agent_id, session_id)
        if session is None: raise HTTPException(404, '会话已删除，无法导出完整聊天记录')
        data = load()
        pid = data.get('project_sessions', {}).get(member_key(user, agent_id, session_id))
        if pid and (viewer or user) != ADMIN: accessible(user, pid)
        records = await asyncio.to_thread(audit_rows, store, {'user_id': user, 'agent_id': agent_id, 'session_id': session_id})
        result = []
        for questions, answer in pairs(await history(storage, user, session_id)):
            linked = [r for r in records if answer.get('id') in r.get('reply_ids', [])]
            source = linked[0]['source'] if linked else getattr(session.origin, 'type', 'user')
            result.append(row_for(user, session_id, session.config.name, data.get('projects', {}).get(pid, {}).get('name', '普通会话'),
                source, '\n\n'.join(plain(q) for q in questions), plain(answer),
                (questions[0] if questions else answer).get('created_at'), linked, answer))
        return response(result, 'conversation.csv')

    @router.get('/audit/sessions/{agent_id}/{session_id}/export.csv')
    async def export_own_session(agent_id: str, session_id: str, request: Request):
        return await session_export(caller(request), agent_id, session_id)

    @router.get('/audit/runs/{run_id}/conversation.csv')
    async def export_run_session(run_id: str, request: Request):
        from portal import ADMIN
        user = caller(request)
        run = await asyncio.to_thread(store.get, run_id)
        if not run or (user != ADMIN and user != run['user_id']):
            raise HTTPException(404, '执行记录不存在')
        return await session_export(run['user_id'], run['agent_id'], run['session_id'], viewer=user)

    @router.get('/audit/export.csv')
    async def export_global(request: Request, user_id: str = '', project_id: str = '',
                            source: str = '', status: str = '', days: int = Query(30, ge=1, le=30)):
        from portal import ADMIN, load
        if caller(request) != ADMIN: raise HTTPException(403, '仅管理员可导出全站审计')
        filters = {}
        if user_id: filters['user_id'] = user_id
        if project_id: filters['project_id'] = None if project_id == '__ordinary__' else project_id
        if source: filters['source'] = source
        if status: filters['status'] = status
        cutoff, end = time.time() - days * 86400, time.time()
        runs = await asyncio.to_thread(audit_rows, store, filters)
        selected = [r for r in runs if cutoff <= r['started'] <= end and r.get('input')]
        cache, seen, result = {}, set(), []
        projects = load().get('projects', {})
        for run in selected:
            key = (run['user_id'], run['agent_id'], run['session_id'])
            if key not in cache:
                all_runs = await asyncio.to_thread(audit_rows, store, dict(zip(('user_id', 'agent_id', 'session_id'), key)))
                messages = await history(storage, key[0], key[2])
                cache[key] = ({answer.get('id'): (questions, answer) for questions, answer in pairs(messages) if answer}, all_runs)
            paired, all_runs = cache[key]
            ids = run.get('reply_ids') or [run['id']]
            for reply_id in ids:
                dedup = (*key, reply_id)
                if dedup in seen: continue
                seen.add(dedup)
                questions, answer = paired.get(reply_id, ([], {}))
                linked = [r for r in all_runs if reply_id in r.get('reply_ids', [])] or [run]
                result.append(row_for(key[0], key[2], run.get('session_name', ''),
                    projects.get(run.get('project_id'), {}).get('name', run.get('project_id') or '普通会话'), run['source'],
                    '\n\n'.join(plain(q) for q in questions) if questions else run['input'],
                    plain(answer) if answer else run.get('output', ''), run['started'], linked, answer))
        return response(result, f'audit-last-{days}-days.csv')
