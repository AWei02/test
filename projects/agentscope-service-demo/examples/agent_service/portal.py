"""Username-based learning portal. Real AgentScope resources, per-user execution.

Set PORTAL_ADMIN to the existing resource owner (default wei). Authorization
configuration is persisted separately from AgentScope's resource storage.
"""
import asyncio
import hashlib
import json
import os
import re
import threading
from pathlib import Path
from uuid import uuid4
from portal_auth import authenticate, ensure_admin_key, new_key, public_user

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from agentscope.app.access import ResourceAccessPolicyBase, ResourceRef, ResourceKind
from agentscope.app.workspace_manager import LocalWorkspaceManager
from agentscope.app.message_bus import MessageBusKeys
from agentscope.skill import Skill

ADMIN = os.getenv('PORTAL_ADMIN', 'wei')
from data_paths import PORTAL_FILE
FILE = PORTAL_FILE
LOCK = threading.RLock()
FIELDS = ('mcps', 'skills', 'knowledge', 'credentials')


def load():
    with LOCK:
        if not FILE.exists():
            save({'users': [{'username': ADMIN, 'email': '', 'role': '管理员',
                             'enabled': True}], 'roles': ['管理员', '普通用户'],
                  'grants': [], 'selections': {}, 'runs': {}})
        return json.loads(FILE.read_text('utf-8'))


def save(data):
    with LOCK:
        tmp = FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), 'utf-8')
        tmp.chmod(0o600)
        os.replace(tmp, FILE)


def user_for(username, data=None):
    data = data or load()
    user = next((u for u in data['users'] if u['username'] == username), None)
    if not user or not user['enabled']:
        raise HTTPException(403, '用户名未开通或已停用，请联系管理员。')
    return user


def grant_for(username, agent, data=None):
    data = data or load()
    user = user_for(username, data)
    rows = [g for g in data['grants'] if g['agent_id'] == agent and
            ((g['subject_type'] == 'user' and g['subject'] == username) or
             (g['subject_type'] == 'role' and g['subject'] == user['role']))]
    if not rows:
        raise HTTPException(403, '没有使用此智能体的权限。')
    return {k: sorted({v for row in rows for v in row[k]}) for k in FIELDS}


def selection_key(user, agent, session):
    return json.dumps([user, agent, session], ensure_ascii=False)


class PortalPolicy(ResourceAccessPolicyBase):
    async def prepare_document_parsing(self, access, viewer, kb_id, filename, config):
        from document_parsing import prepare
        return await prepare(access, viewer, kb_id, filename, config)

    async def search_knowledge(self, knowledge, documents, access, viewer, kb_id,
                               options, queries, top_k=5, score_threshold=None, filter_hits=None):
        from retrieval import RetrievalSettings, retrieve
        configured = load().get('knowledge_retrieval', {}).get(kb_id)
        if options is None and configured is None:
            from document_chunking import expand_parent_hits
            return expand_parent_hits(await knowledge.search(queries, top_k=top_k, score_threshold=score_threshold))
        settings = RetrievalSettings.model_validate(options if options is not None else configured)
        return await retrieve(knowledge, documents, queries, settings, access, viewer, filter_hits)

    def prepare_document_acl(self, kb_id, mode, users, roles):
        data = load()
        mode = mode or data.get('knowledge_defaults', {}).get(kb_id, 'inherit')
        users, roles = sorted(set(users or [])), sorted(set(roles or []))
        if mode != 'custom':
            return mode, [], []
        if not set(users) <= {u['username'] for u in data['users']} or not set(roles) <= set(data['roles']):
            raise HTTPException(400, '指定的用户或角色不存在')
        return mode, users, roles

    def can_read_document(self, viewer, document):
        user = user_for(viewer)
        if viewer == ADMIN or viewer == document.user_id:
            return True
        acl = document.data
        return acl.access_mode == 'inherit' or (acl.access_mode == 'custom' and (
            viewer in acl.access_users or user['role'] in acl.access_roles))

    def mcp_references(self, resource_id):
        return [g['id'] for g in load()['grants'] if resource_id in g.get('mcps', [])]

    def skill_references(self, resource_id):
        return [g['id'] for g in load()['grants'] if resource_id in g.get('skills', [])]

    def knowledge_references(self, resource_id):
        return [g['id'] for g in load()['grants'] if resource_id in g.get('knowledge', [])]

    def credential_references(self, credential_id):
        """Return portal grant IDs that still reference a credential."""
        data = load()
        return [
            grant['id'] for grant in load()['grants']
            if credential_id in grant.get('credentials', [])
        ] + ['知识库检索策略:' + kb_id for kb_id, config in data.get('knowledge_retrieval', {}).items()
             if config.get('rerank_enabled') and config.get('credential_id') == credential_id
        ] + ['知识库解析策略:' + kb_id for kb_id, config in data.get('knowledge_parsing', {}).items()
             if config.get('engine') == 'llm' and config.get('credential_id') == credential_id]

    async def list_accessible(self, viewer_id, kind, storage):
        if viewer_id == ADMIN:
            return []
        data = load()
        user = user_for(viewer_id, data)
        grants = [g for g in data['grants'] if
                  (g['subject_type'] == 'user' and g['subject'] == viewer_id) or
                  (g['subject_type'] == 'role' and g['subject'] == user['role'])]
        field = {ResourceKind.AGENT: 'agent_id', ResourceKind.CREDENTIAL: 'credentials',
                 ResourceKind.KNOWLEDGE_BASE: 'knowledge'}[kind]
        ids = {g[field] for g in grants} if field == 'agent_id' else {
            value for g in grants for value in g[field]}
        return [ResourceRef(kind=kind, owner_id=ADMIN, resource_id=value) for value in ids]


class PortalWorkspace:
    """A per-run view; default MCPs and another session's selection never leak in."""
    def __init__(self, base, storage, username, agent, session, channel_capabilities=None):
        self.base, self.storage = base, storage
        self.username, self.agent, self.session = username, agent, session
        self.channel_capabilities = channel_capabilities

    def __getattr__(self, name):
        return getattr(self.base, name)

    def selected(self, field):
        if self.channel_capabilities is not None:
            return set(self.channel_capabilities.get(field, []))
        data = load()
        selected = data['selections'].get(
            selection_key(self.username, self.agent, self.session), {},
        )
        # Administrators use the same explicit per-session capability
        # selection as other users.  Previously they inherited every MCP in
        # the workspace, so a stale or unavailable server could prevent all
        # chat replies (including plain messages and RAG queries).
        if self.username == ADMIN:
            if field == 'skills':
                from skill_packages import ROOT
                installed = {p.name for p in ROOT.iterdir() if p.is_dir()} if ROOT.exists() else set()
                return set(selected.get(field, [])) & installed
            return set(selected.get(field, []))
        allowed = grant_for(self.username, self.agent, data)
        return set(selected.get(field, [])) & set(allowed[field])

    async def add_mcp(self, client, **kwargs):
        # The administrator's workspace picker must persist the same per-session
        # selection that list_mcps reads. Merely adding to the base workspace
        # left the MCP invisible to the next chat run.
        if self.username != ADMIN or self.channel_capabilities is not None:
            raise HTTPException(403, '请通过已授权的会话能力选择 MCP。')
        record = await self.storage.get_mcp_by_name(ADMIN, client.name)
        if record is not None and not record.enabled:
            raise ValueError('此 MCP 已停用。')
        await self.base.add_mcp(client, **kwargs)
        if record is None:
            from agentscope.app.storage import MCPRecord
            record = MCPRecord(user_id=ADMIN, client=client)
            record.id = await self.storage.upsert_mcp(ADMIN, record)
        with LOCK:
            data = load()
            selected = data['selections'].setdefault(
                selection_key(self.username, self.agent, self.session), {})
            selected['mcps'] = sorted(set(selected.get('mcps', [])) | {record.id})
            save(data)

    async def remove_mcp(self, name, **kwargs):
        if self.username != ADMIN or self.channel_capabilities is not None:
            raise HTTPException(403, '请通过已授权的会话能力选择 MCP。')
        record = await self.storage.get_mcp_by_name(ADMIN, name)
        await self.base.remove_mcp(name, **kwargs)
        if record is not None:
            with LOCK:
                data = load()
                selected = data['selections'].setdefault(
                    selection_key(self.username, self.agent, self.session), {})
                selected['mcps'] = [mid for mid in selected.get('mcps', []) if mid != record.id]
                save(data)

    async def list_mcps(self, **kwargs):
        records = await self.storage.list_mcps(ADMIN)
        result = []
        for record in records:
            if record.id in self.selected('mcps') and record.enabled:
                # Workspace owns connection lifecycle and maintains per-session clients.
                existing = {m.name: m for m in await self.base.list_mcps(**kwargs)}
                current = existing.get(record.client.name)
                if current and (current.mcp_config != record.client.mcp_config
                                or current.is_stateful != record.client.is_stateful):
                    await self.base.remove_mcp(record.client.name, **kwargs)
                    existing.pop(record.client.name)
                present = set(existing)
                if record.client.name not in present:
                    from agentscope.mcp import MCPClient
                    await self.base.add_mcp(MCPClient.model_validate(record.client.model_dump()), **kwargs)
                result.extend(m for m in await self.base.list_mcps(**kwargs)
                              if m.name == record.client.name)
        return result

    async def list_skills(self, **kwargs):
        # Skill instructions use the installed library snapshot. No unapproved
        # files or shell tools are granted by selecting an instruction skill.
        from skill_packages import package_skill
        result = []
        for record in await self.storage.list_skills(ADMIN):
            if record.id in self.selected('skills') and record.enabled:
                package = package_skill(record)
                result.append(package[0] if package else Skill(name=record.name,
                    description=record.description, dir=self.base.workdir,
                    markdown=record.markdown, updated_at=0))
        if self.username == ADMIN and self.channel_capabilities is None:
            result.extend(s for s in await self.base.list_skills(**kwargs)
                          if s.name not in {r.name for r in result})
        return result

    async def list_tools(self):
        from skill_packages import RunSkill, ROOT
        tools = await self.base.list_tools() if self.username == ADMIN and self.channel_capabilities is None else []
        from project_files import ProjectFiles
        tools.append(ProjectFiles(self))
        # Graph retrieval complements the stock vector-search RAG tool.  It
        # only appears for a session that explicitly selected knowledge bases
        # and when Neo4j has been configured; unbuilt graphs simply return no
        # facts and never block an ordinary chat reply.
        knowledge_ids = sorted(self.selected('knowledge'))
        graph_store = getattr(getattr(self.storage, 'app', None), 'state', None)
        graph_store = getattr(graph_store, 'graph_rag_store', None)
        if graph_store is None:
            # The app owns this singleton; the fallback keeps custom test
            # workspaces and channel sessions independent of FastAPI internals.
            from graph_rag import GraphRagStore
            graph_store = GraphRagStore.from_env()
        if graph_store and knowledge_ids:
            from graph_rag import GraphSearchTool
            tools.append(GraphSearchTool(graph_store, knowledge_ids, workspace=self))
        if any((ROOT / sid / 'manifest.json').is_file() for sid in self.selected('skills')):
            tools.append(RunSkill(self))
        return tools

    def filter_tool_access(self, tools, groups):
        if self.username == ADMIN and self.channel_capabilities is None:
            return tools, groups
        from skill_packages import RunSkill
        from project_files import ProjectFiles
        # Portal users get approved MCP tools + RAG + skill instructions.
        # Team/scheduler/host filesystem tools would bypass these resource grants.
        return [t for t in tools if isinstance(t, (RunSkill, ProjectFiles)) or (t.__class__.__module__ == 'agentscope.middleware._rag'
                and t.name == 'search_knowledge') or (t.__class__.__module__ == 'graph_rag'
                and t.name == 'search_knowledge_graph')], []


class PortalWorkspaceManager(LocalWorkspaceManager):
    async def configure_channel_session(self, record, agent_id, session_id):
        from channel_projects import prepare
        from agentscope.app.storage import SessionKnowledgeConfig
        selected = await prepare(self._storage, record, agent_id, session_id)
        return {'knowledge_config': SessionKnowledgeConfig(knowledge_base_ids=selected['knowledge']) if selected and selected['knowledge'] else None} if selected is not None else {}

    async def get_workspace(self, user_id, agent_id, session_id, workspace_id=None):
        selected = None
        session = await self._storage.get_session(user_id, agent_id, session_id)
        channel_id = getattr(getattr(session, 'origin', None), 'channel_id', None)
        if channel_id:
            record = await self._storage.get_channel(channel_id)
            if record is None or record.user_id != user_id:
                raise HTTPException(403, '频道不存在或无访问权限')
            from channel_projects import prepare
            selected = await prepare(self._storage, record, agent_id, session_id)
        if user_id == ADMIN and selected is None:
            base = await super().get_workspace(user_id, agent_id, session_id, workspace_id)
            return PortalWorkspace(base, self._storage, user_id, agent_id, session_id)
        if user_id != ADMIN:
            grant_for(user_id, agent_id)
        # The stock LocalWorkspaceManager derives its directory from agent_id
        # only. Hash all three identities to isolate shared-agent users/sessions.
        isolated = hashlib.sha256(selection_key(user_id, agent_id, session_id).encode()).hexdigest()
        # Managed workspaces have no default capabilities to seed/connect.
        from agentscope.workspace import LocalWorkspace
        cache_key = 'portal-' + isolated + (hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest() if selected is not None else '')
        async with self._lock:
            if cache_key not in self._cache:
                import time
                base = LocalWorkspace(workspace_id=cache_key,
                    workdir=os.path.join(self._basedir, isolated), default_mcps=[])
                await base.initialize()
                self._cache[cache_key] = (base, time.monotonic())
            base = self._cache[cache_key][0]
        return PortalWorkspace(base, self._storage, user_id, agent_id, session_id, selected)


class RoleInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    confirmed: bool = False


class UserInput(BaseModel):
    username: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_.@+-]+$')
    email: str = Field(default='', max_length=200)
    role: str = Field(default='普通用户', min_length=1, max_length=80)
    enabled: bool = True


class GrantInput(BaseModel):
    id: str | None = None
    subject_type: str = Field(pattern='^(user|role)$')
    subject: str
    agent_id: str
    mcps: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)
    credentials: list[str] = Field(default_factory=list)


class SelectionInput(BaseModel):
    mcps: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)


class GraphBuildInput(BaseModel):
    """The operator explicitly chooses the model charged for extraction."""
    chat_model_config: dict
    max_chunks_per_document: int = Field(default=30, ge=1, le=100)
    rules_revision: int = Field(ge=0)


async def catalog(storage):
    agents, mcps, skills, knowledge, credentials = await asyncio.gather(
        storage.list_agents(ADMIN), storage.list_mcps(ADMIN), storage.list_skills(ADMIN),
        storage.list_knowledge_bases(ADMIN), storage.list_credentials(ADMIN))
    return {
        'agents': [{'id': r.id, 'name': r.data.name} for r in agents],
        'mcps': [{'id': r.id, 'name': r.client.name} for r in mcps if r.enabled],
        'skills': [{'id': r.id, 'name': r.name} for r in skills if r.enabled],
        'knowledge': [{'id': r.id, 'name': r.data.name} for r in knowledge],
        'credentials': [{'id': r.id, 'name': r.data.get('name', r.data.get('type', r.id))}
                        for r in credentials],
    }


def install_portal(app):
    ensure_admin_key()
    # Local model/MCP endpoints must bypass an inherited outbound HTTP proxy.
    bypass = os.environ.get('NO_PROXY', os.environ.get('no_proxy', ''))
    os.environ['NO_PROXY'] = ','.join(dict.fromkeys(filter(None,
        [*bypass.split(','), '127.0.0.1', 'localhost', '::1'])))
    router = APIRouter(prefix='/portal', tags=['portal'])

    def caller(request):
        return request.headers.get('x-user-id', '')

    def require_admin(request):
        username = caller(request)
        user_for(username)
        if username != ADMIN:
            raise HTTPException(403, '仅管理员可执行此操作。')

    from skill_packages import install_routes
    install_routes(router, app, require_admin)
    from file_catalog import install_routes as install_file_catalog
    install_file_catalog(router, app)
    from custom_mcps import install_routes as install_custom_mcps
    install_custom_mcps(router, app, require_admin)
    from project_files import install_routes as install_projects
    install_projects(router, app)
    from project_transfer import install_routes as install_transfer
    install_transfer(router, app)
    if getattr(app.state, "audit_observer", None) is not None:
        from execution_audit import install_routes as install_execution_audit
        install_execution_audit(router, app)
    from channel_audit import install_routes as install_channel_audit
    install_channel_audit(router, app, require_admin)
    from branding import install_routes as install_branding
    install_branding(router, require_admin)
    from document_permissions import install_routes as install_document_permissions
    install_document_permissions(router, app, require_admin)
    from retrieval import install_routes as install_retrieval
    install_retrieval(router, app, require_admin, caller)
    from graph_rules import install_routes as install_graph_rules
    install_graph_rules(router, app, require_admin)
    from document_parsing import install_routes as install_parsing, parse_document
    app.state.document_parser = parse_document
    install_parsing(router, app, require_admin, caller)
    from document_stages import install_routes as install_stages, process_stage
    app.state.document_stage_processor = process_stage
    install_stages(router, app, require_admin, caller)

    def graph_store():
        store = getattr(app.state, 'graph_rag_store', None)
        if store is None:
            raise HTTPException(503, 'GraphRAG 尚未配置 Neo4j。')
        return store

    @router.get('/knowledge-graph/{knowledge_base_id}')
    async def graph_snapshot(knowledge_base_id: str, request: Request):
        require_admin(request)
        try:
            store = graph_store()
            await store.ensure_ready()
            return await store.snapshot(knowledge_base_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(503, f'GraphRAG 不可用：{exc}') from exc

    @router.post('/knowledge-graph/{knowledge_base_id}/build')
    async def build_graph(knowledge_base_id: str, body: GraphBuildInput, request: Request):
        """Build a graph from existing chunks without changing vector RAG."""
        require_admin(request)
        from graph_rules import BUILD_LOCKS, GraphRules, state_for, validate_extraction, finish_build
        build_lock = BUILD_LOCKS.setdefault(knowledge_base_id, asyncio.Lock())
        if build_lock.locked():
            raise HTTPException(409, '该知识库正在构建图谱')
        await build_lock.acquire()
        try:
            state = state_for(knowledge_base_id)
            if state['revision'] != body.rules_revision:
                raise HTTPException(409, '抽取规则已更新，请刷新规则后再构建')
            rules = GraphRules.model_validate(state['rules'])
            from agentscope.app.storage import ChatModelConfig
            from agentscope.app._service._model import get_model
            from graph_rag import extract_chunk_graph

            username = caller(request)
            store = graph_store()
            await store.ensure_ready()
            record = await app.state.resource_access_service.resolve_knowledge_base(
                username, knowledge_base_id,
            )
            knowledge = await app.state.knowledge_base_manager.get_knowledge(
                record.user_id, knowledge_base_id,
            )
            model = await get_model(
                username, ChatModelConfig(**body.chat_model_config),
                app.state.resource_access_service,
            )
            documents = await app.state.storage.list_knowledge_documents(
                record.user_id, knowledge_base_id,
            )
            processed = relations = rejected = 0
            staged, pending = [], []
            entity_types = {}
            for document in documents:
                if document.status != 'ready':
                    continue
                if document.data.chunk_count > body.max_chunks_per_document:
                    raise HTTPException(400, f'文件 {document.data.filename} 有 {document.data.chunk_count} 个分块，超过本次上限；请调高上限，旧图谱未修改。')
                chunks = await knowledge.list_chunks(
                    document.id, limit=body.max_chunks_per_document,
                )
                for chunk in chunks:
                    content = chunk.content
                    text = str(content.get('text', '')) if isinstance(content, dict) else getattr(content, 'text', '')
                    if not text.strip():
                        continue
                    if len(text) > 12000:
                        raise HTTPException(400, f'文件 {document.data.filename} 的分块 {chunk.chunk_index + 1} 超过12000字符，请先缩小分块；旧图谱未修改。')
                    extraction = await extract_chunk_graph(model, text, rules)
                    extraction, proposals, dropped = validate_extraction(extraction, rules)
                    for entity in extraction.entities:
                        if entity.name in entity_types and entity_types[entity.name] != entity.type:
                            raise HTTPException(422, f'实体“{entity.name}”在不同分块中类型冲突，请统一类型或名称；旧图谱未修改。')
                        entity_types[entity.name] = entity.type
                    pending.extend({**p, 'document_id':document.id, 'filename':document.data.filename,
                                    'chunk_index':chunk.chunk_index} for p in proposals)
                    rejected += dropped
                    relations += len(extraction.relations)
                    staged.append((document.id, document.data.filename, chunk.chunk_index, extraction))
                    processed += 1
            if not staged:
                raise HTTPException(400, '没有可抽取的就绪文本分块，旧图谱未修改。')
            await store.replace_knowledge(knowledge_base_id, staged)
            finish_build(knowledge_base_id, state['revision'], pending,
                         {'processed_chunks':processed, 'relations':relations, 'entities':len(entity_types), 'rejected':rejected})
            snapshot = await store.snapshot(knowledge_base_id)
            return {**snapshot, 'processed_chunks': processed, 'relations': relations}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f'GraphRAG 构建失败：{exc}') from exc
        finally:
            build_lock.release()

    @router.get('/me')
    async def me(request: Request):
        username = caller(request)
        return {**public_user(user_for(username)), 'is_admin': username == ADMIN}

    @router.post('/models/{credential_id}/refresh')
    async def refresh_models(credential_id: str, request: Request):
        from agentscope.app._router._credential import refresh_official_models
        require_admin(request)
        result = await refresh_official_models(
            credential_id, caller(request), app.state.storage,
            app.state.resource_access_service,
        )
        with LOCK:
            data = load()
            previous = data.setdefault('official_models', {}).get(credential_id, {})
            # Models are opt-in. The first refresh leaves every model
            # unchecked; later refreshes preserve choices but do not enable
            # newly discovered models on the user's behalf.
            previous_enabled = set(previous.get('enabled_models', []))
            result['enabled_models'] = [
                name for name in result['models']
                if previous.get('selection_initialized') and name in previous_enabled
            ]
            result['model_types'] = {
                name: category for name, category in previous.get('model_types', {}).items()
                if name in result['models']
            }
            result['model_configs'] = {
                name: config for name, config in previous.get('model_configs', {}).items()
                if name in result['models']
            }
            result['selection_initialized'] = True
            data['official_models'][credential_id] = result
            save(data)
        return result

    @router.get('/models/{credential_id}')
    async def available_models(credential_id: str, request: Request):
        from agentscope.credential import CredentialFactory
        record = await app.state.resource_access_service.resolve_credential(
            caller(request), credential_id,
        )
        cached = load().get('official_models', {}).get(credential_id)
        if cached is None:
            # An OpenAI-compatible credential can point at any provider.
            # There is no trustworthy built-in catalogue before /models has
            # been queried, and attempting to load OpenAI's own cards can
            # fail for a third-party base URL.
            if record.data.get('type') == 'openai_credential':
                return {'models': [], 'enabled_models': [], 'fetched_at': None}
            model_cls = CredentialFactory.from_dict(record.data).get_chat_model_class()
            builtin = {card.name: card.model_dump(mode='json') for card in model_cls.list_models()}
            return {'models': list(builtin.values()), 'enabled_models': [], 'fetched_at': None}
        try:
            model_cls = CredentialFactory.from_dict(record.data).get_chat_model_class()
            builtin = {card.name: card.model_dump(mode='json') for card in model_cls.list_models()}
            parameter_schema = model_cls.Parameters.model_json_schema()
        except Exception:
            # Live provider model IDs are still usable even where framework
            # static metadata is unavailable for a compatibility endpoint.
            builtin = {}
            parameter_schema = {}
        cards = []
        for name in cached['models']:
            # Unknown metadata is not inferred from a different model's card.
            card = builtin.get(name) or {
                'type': 'chat_model', 'name': name, 'label': name, 'status': 'active',
                'input_types': ['text/plain'], 'output_types': ['text/plain'],
                'context_size': None, 'output_size': None,
                'parameter_schema': parameter_schema,
                'parameters_overrides': {},
            }
            category = cached.get('model_types', {}).get(name)
            if category:
                card = {**card, 'category': category}
            config = cached.get('model_configs', {}).get(name, {})
            if category == 'llm' and isinstance(config.get('vision'), bool):
                input_types = [mime for mime in card['input_types']
                               if not mime.startswith('image/')]
                if config['vision']:
                    input_types.append('image/*')
                card = {**card, 'input_types': input_types}
            cards.append(card)
        enabled_models = cached.get('enabled_models', []) if cached.get('selection_initialized') else []
        return {'models': cards, 'enabled_models': enabled_models,
                'model_types': cached.get('model_types', {}),
                'model_configs': cached.get('model_configs', {}),
                'fetched_at': cached['fetched_at']}

    @router.put('/models/{credential_id}/enabled')
    async def set_enabled_models(credential_id: str, body: dict, request: Request):
        require_admin(request)
        enabled = body.get('enabled_models')
        model_types = body.get('model_types', {})
        model_configs = body.get('model_configs', {})
        if not isinstance(enabled, list) or not all(isinstance(name, str) for name in enabled):
            raise HTTPException(400, 'enabled_models 必须是模型名称数组')
        if (not isinstance(model_types, dict) or
                not all(isinstance(name, str) and category in
                        {'llm', 'rerank', 'embedding', 'stt', 'tts'}
                        for name, category in model_types.items())):
            raise HTTPException(400, 'model_types 包含无效的模型类型')
        if (not isinstance(model_configs, dict) or
                not all(isinstance(name, str) and isinstance(config, dict)
                        for name, config in model_configs.items())):
            raise HTTPException(400, 'model_configs 必须是模型配置对象')
        for config in model_configs.values():
            if 'vision' in config and not isinstance(config['vision'], bool):
                raise HTTPException(400, 'vision 必须是布尔值')
        with LOCK:
            data = load()
            cached = data.get('official_models', {}).get(credential_id)
            if cached is None:
                from agentscope.credential import CredentialFactory
                record = await app.state.resource_access_service.resolve_credential(
                    caller(request), credential_id,
                )
                builtin = CredentialFactory.from_dict(record.data).get_chat_model_class().list_models()
                cached = {
                    'models': [card.name for card in builtin],
                    'enabled_models': [],
                    'selection_initialized': True,
                    'fetched_at': None,
                }
                data.setdefault('official_models', {})[credential_id] = cached
            available = set(cached['models'])
            if not set(enabled) <= available:
                raise HTTPException(400, '包含不属于此凭证的模型')
            if not set(model_types) <= available:
                raise HTTPException(400, '模型类型包含不属于此凭证的模型')
            if not set(model_configs) <= available:
                raise HTTPException(400, '模型配置包含不属于此凭证的模型')
            configured_enabled = []
            for name in enabled:
                config = model_configs.get(name)
                category = model_types.get(name)
                # Older saved selections predate per-model configuration.
                # Demote them to disabled instead of making one stale row
                # prevent the user from saving another model's configuration.
                if config is None or category is None:
                    continue
                def positive(key):
                    value = config.get(key)
                    return isinstance(value, int) and value > 0
                if category == 'llm' and not (positive('context_size') and positive('output_size')):
                    continue
                if category == 'embedding' and not positive('dimensions'):
                    continue
                if category == 'rerank' and not positive('context_size'):
                    continue
                configured_enabled.append(name)
            cached['enabled_models'] = [
                name for name in cached['models'] if name in set(configured_enabled)
            ]
            cached['model_types'] = {
                name: model_types[name] for name in cached['models'] if name in model_types
            }
            cached['model_configs'] = {
                name: model_configs[name] for name in cached['models'] if name in model_configs
            }
            cached['selection_initialized'] = True
            save(data)
        return {
            'enabled_models': cached['enabled_models'],
            'skipped_models': [name for name in enabled if name not in configured_enabled],
        }

    @router.get('/knowledge-bases/embedding-models')
    async def portal_embedding_models(request: Request):
        """Expose enabled, provider-catalogued embedding models to KB setup."""
        policy = await app.state.knowledge_base_manager.get_dimension_policy()
        credentials = await app.state.resource_access_service.list_resource(
            caller(request), ResourceKind.CREDENTIAL,
        )
        data = load()
        providers = []
        for credential in credentials:
            cached = data.get('official_models', {}).get(credential.id, {})
            enabled = set(cached.get('enabled_models', [])) if cached.get(
                'selection_initialized',
            ) else set()
            models = []
            # Providers are not required to return metadata from ``/models``.
            # A manually typed and configured model is still a valid KB
            # candidate, so start with the provider's model IDs and enrich
            # them when metadata is available.
            model_names = set(cached.get('models', [])) | set(
                cached.get('model_metadata', {}),
            )
            for name in sorted(model_names):
                metadata = cached.get('model_metadata', {}).get(name, {})
                if cached.get('model_types', {}).get(name) != 'embedding' or name not in enabled:
                    continue
                dimensions = cached.get('model_configs', {}).get(name, {}).get(
                    'dimensions', metadata.get('dimensions'),
                )
                if not isinstance(dimensions, int) or dimensions <= 0:
                    continue
                if policy.dimension is not None and dimensions != policy.dimension:
                    continue
                models.append({
                    'type': 'embedding_model', 'name': name, 'label': name,
                    'status': 'active', 'input_types': ['text/plain'],
                    'output_types': ['application/x-embedding'],
                    'context_size': metadata.get('context_size'),
                    'dimensions': dimensions, 'supported_dimensions': None,
                    'parameter_schema': {}, 'parameter_overrides': {},
                })
            if models:
                providers.append({
                    'credential': credential.model_dump(mode='json'),
                    'models': models,
                })
        return {'providers': providers, 'policy': policy.model_dump(mode='json')}

    @router.get('/admin')
    async def state(request: Request):
        require_admin(request)
        data = load()
        return {k: data[k] for k in ('users', 'roles', 'grants')} | {
            'catalog': await catalog(app.state.storage)}

    @router.get('/allowed/{agent_id}')
    async def allowed(agent_id: str, request: Request):
        return grant_for(caller(request), agent_id)

    @router.put('/users')
    async def put_user(body: UserInput, request: Request):
        require_admin(request)
        if body.username == ADMIN and not body.enabled:
            raise HTTPException(400, '不能停用初始管理员。')
        if body.username != ADMIN and body.role == '管理员':
            raise HTTPException(400, '管理员角色仅用于初始管理员，普通用户请选择其他角色。')
        with LOCK:
            data = load()
            if body.role not in data['roles']:
                raise HTTPException(400, '角色不存在，请先在角色管理中创建。')
            previous = next((u for u in data['users'] if u['username'] == body.username), {})
            record = body.model_dump()
            if previous.get('login_key'):
                record['login_key'] = previous['login_key']
            data['users'] = [u for u in data['users'] if u['username'] != body.username]
            data['users'].append(record)
            save(data)
        return body

    @router.post('/users/{username}/key')
    async def regenerate_login_key(username: str, request: Request):
        require_admin(request)
        with LOCK:
            data = load()
            user = next((u for u in data['users'] if u['username'] == username), None)
            if user is None:
                raise HTTPException(404, '用户不存在，请先保存用户资料。')
            user['login_key'] = new_key()
            save(data)
            return {'login_key': user['login_key']}

    @router.post('/roles')
    async def create_role(body: RoleInput, request: Request):
        require_admin(request)
        name = body.name.strip()
        if not name:
            raise HTTPException(400, '角色名称不能为空。')
        with LOCK:
            data = load()
            if name in data['roles']:
                raise HTTPException(409, '角色已存在。')
            data['roles'].append(name)
            save(data)
        return {'ok': True}

    @router.post('/roles/delete')
    async def delete_role(body: RoleInput, request: Request):
        require_admin(request)
        if not body.confirmed:
            raise HTTPException(400, '请先确认删除角色。')
        with LOCK:
            data = load()
            if body.name not in data['roles']:
                raise HTTPException(404, '角色不存在。')
            users = [u['username'] for u in data['users'] if u['role'] == body.name]
            grants = [g['id'] for g in data['grants'] if g['subject_type'] == 'role' and g['subject'] == body.name]
            if users or grants:
                raise HTTPException(409, '角色仍被引用，不能删除。用户：' + ('、'.join(users) or '无') + '；访问授权：' + ('、'.join(grants) or '无'))
            data['roles'].remove(body.name)
            save(data)
        return {'ok': True}

    @router.put('/grants')
    async def put_grant(body: GrantInput, request: Request):
        require_admin(request)
        resources = await catalog(app.state.storage)
        if body.agent_id not in {r['id'] for r in resources['agents']}:
            raise HTTPException(400, '请选择真实存在的智能体。')
        for field in FIELDS:
            if not set(getattr(body, field)) <= {r['id'] for r in resources[field]}:
                raise HTTPException(400, f'{field} 包含不存在或停用的资源。')
        with LOCK:
            data = load()
            subjects = {u['username'] for u in data['users']} if body.subject_type == 'user' else set(data['roles'])
            if body.subject not in subjects:
                raise HTTPException(400, '用户或角色不存在。')
            data['grants'] = [g for g in data['grants'] if g['id'] != body.id and not all(
                g[k] == getattr(body, k) for k in ('subject_type', 'subject', 'agent_id'))]
            data['grants'].append(body.model_dump() | {'id': body.id or uuid4().hex})
            save(data)
        return {'ok': True}

    @router.delete('/users/{username}')
    async def delete_user(username: str, request: Request):
        require_admin(request)
        if username == ADMIN:
            raise HTTPException(400, '不能删除初始管理员。')
        with LOCK:
            data = load()
            data['users'] = [u for u in data['users'] if u['username'] != username]
            data['grants'] = [g for g in data['grants'] if not (
                g['subject_type'] == 'user' and g['subject'] == username)]
            for field in ('selections', 'runs'):
                data[field] = {k: v for k, v in data[field].items() if json.loads(k)[0] != username}
            save(data)
        return {'ok': True}

    @router.delete('/grants/{grant_id}')
    async def revoke(grant_id: str, request: Request):
        require_admin(request)
        with LOCK:
            data = load()
            data['grants'] = [g for g in data['grants'] if g['id'] != grant_id]
            save(data)
        return {'ok': True}

    @router.get('/capabilities/{agent_id}/{session_id}')
    async def capabilities(agent_id: str, session_id: str, request: Request):
        username = caller(request)
        allowed = grant_for(username, agent_id)
        session = await app.state.storage.get_session(username, agent_id, session_id)
        if session is None:
            raise HTTPException(404, '会话不存在。')
        resources = await catalog(app.state.storage)
        selected = load()['selections'].get(selection_key(username, agent_id, session_id), {})
        return {'has_selection': selection_key(username, agent_id, session_id) in load()['selections'],
                'has_model': bool(allowed['credentials']), 'catalog': {k: [r for r in resources[k] if r['id'] in allowed[k]]
                            for k in ('mcps', 'skills', 'knowledge')},
                'selected': {k: [v for v in selected.get(k, []) if v in allowed[k]]
                             for k in ('mcps', 'skills', 'knowledge')}}

    @router.put('/capabilities/{agent_id}/{session_id}')
    async def select(body: SelectionInput, agent_id: str, session_id: str, request: Request):
        username = caller(request)
        allowed = grant_for(username, agent_id)
        values = body.model_dump()
        if any(not set(values[k]) <= set(allowed[k]) for k in values):
            raise HTTPException(403, '选择了未授权的能力。')
        lock_key = MessageBusKeys.session_lock(session_id)
        if await app.state.message_bus.is_locked(lock_key):
            raise HTTPException(409, '智能体正在回复，请结束后再修改能力。')
        async with app.state.message_bus.acquire_lock(lock_key):
            session = await app.state.storage.get_session(username, agent_id, session_id)
            if session is None:
                raise HTTPException(404, '会话不存在。')
            from agentscope.app.storage import SessionKnowledgeConfig
            config = session.config.model_copy(update={'knowledge_config':
                SessionKnowledgeConfig(knowledge_base_ids=body.knowledge) if body.knowledge else None})
            await app.state.storage.upsert_session(username, agent_id, config, session_id=session_id)
            with LOCK:
                data = load()
                data['selections'][selection_key(username, agent_id, session_id)] = values
                save(data)
        return {'ok': True}

    app.include_router(router)

    agent_grant_lock = asyncio.Lock()

    class PortalGate(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            try:
                if request.method == 'OPTIONS':
                    return await call_next(request)
                # Strip untrusted identity before even the signed-download branch.
                request.scope['headers'] = [(k, v) for k, v in request.scope['headers']
                                            if k.lower() != b'x-user-id']
                if hasattr(request, '_headers'):
                    del request._headers
                # These existing download handlers validate their signed token.
                if request.method == 'GET' and request.query_params.get('token') and (
                    request.url.path == '/workspace/files' or re.fullmatch(
                        r'/knowledge_bases/[^/]+/documents/[^/]+', request.url.path)):
                    return await call_next(request)
                username = authenticate(request.headers.get('authorization', ''))
                # All downstream AgentScope routes consume the verified identity.
                # Never trust a user-supplied X-User-ID, including duplicate headers.
                request.scope['headers'] = [
                    (k, v) for k, v in request.scope['headers']
                    if k.lower() != b'x-user-id'
                ] + [(b'x-user-id', username.encode())]
                if hasattr(request, '_headers'):
                    del request._headers
                if username == ADMIN:
                    path = request.url.path.rstrip('/')
                    agent_delete = request.method == 'DELETE' and re.fullmatch(r'/agent/[^/]+', path)
                    credential_delete = request.method == 'DELETE' and re.fullmatch(r'/credential/[^/]+', path)
                    library_delete = request.method == 'DELETE' and re.fullmatch(r'/(mcp|skill|knowledge_bases)/[^/]+', path)
                    if agent_delete or credential_delete or library_delete or (path == '/portal/grants' and request.method == 'PUT'):
                        async with agent_grant_lock:
                            if library_delete:
                                kind, resource_id = path.strip('/').split('/')
                                field, label = {'mcp':('mcps','MCP'), 'skill':('skills','技能'), 'knowledge_bases':('knowledge','知识库')}[kind]
                                refs = [g['id'] for g in load()['grants'] if resource_id in g.get(field, [])]
                                if refs:
                                    raise HTTPException(409, label + '仍被访问授权引用，不能删除。请先解除授权。授权编码：' + '、'.join(refs))
                            if agent_delete:
                                aid = path.rsplit('/',1)[-1]
                                refs = [g for g in load()['grants'] if g['agent_id'] == aid]
                                if refs:
                                    raise HTTPException(409, '智能体仍被访问授权引用，不能删除。授权编码：' + '、'.join(g['id'] for g in refs))
                            if credential_delete:
                                credential_id = path.rsplit('/', 1)[-1]
                                refs = [g for g in load()['grants']
                                        if credential_id in g.get('credentials', [])]
                                if refs:
                                    raise HTTPException(
                                        409,
                                        '凭证仍被访问授权引用，不能删除。授权编码：' +
                                        '、'.join(g['id'] for g in refs),
                                    )
                            return await call_next(request)
                    if path == '/chat' and request.method == 'POST':
                        body = await request.json()
                        aid, sid = body.get('agent_id'), body.get('session_id')
                        session = await app.state.storage.get_session(username, aid, sid) if aid and sid else None
                        cid = getattr(getattr(session, 'origin', None), 'channel_id', None)
                        if cid:
                            record = await app.state.storage.get_channel(cid)
                            if record is None or record.user_id != username:
                                raise HTTPException(403, '频道不存在或无访问权限')
                            from channel_projects import prepare
                            from agentscope.app.storage import SessionKnowledgeConfig
                            selected = await prepare(app.state.storage, record, aid, sid)
                            if selected is not None:
                                config = session.config.model_copy(update={'knowledge_config': SessionKnowledgeConfig(knowledge_base_ids=selected['knowledge']) if selected['knowledge'] else None})
                                await app.state.storage.upsert_session(username, aid, config, session_id=sid)
                    if request.method in ('POST', 'PATCH') and (path == '/channels' or (request.method == 'PATCH' and path.startswith('/channels/'))):
                        body = await request.json()
                        record = await app.state.storage.get_channel(path.split('/')[-1]) if request.method == 'PATCH' else None
                        settings = body.get('session', record.session.model_dump() if record else {})
                        routing = body.get('routing', record.routing.model_dump() if record else {})
                        if record and record.session.project_id and settings.get('project_id') != record.session.project_id:
                            raise HTTPException(409, '绑定项目后不可切换，请新建频道')
                        from channel_projects import validate
                        await validate(app.state.storage, username, settings, routing.get('bindings', []))
                    return await call_next(request)
                path = request.url.path.rstrip('/')
                if path.startswith('/portal'):
                    return await call_next(request)
                if path == '/agent' and request.method == 'GET':
                    entries = await app.state.resource_access_service.list_resource(username, ResourceKind.AGENT)
                    allowed_ids = {ref.resource_id for ref in await PortalPolicy().list_accessible(
                        username, ResourceKind.AGENT, app.state.storage)}
                    entries = [view.model_dump(mode='json') | {'editable': False}
                               for view in entries if view.id in allowed_ids and view.user_id == ADMIN]
                    return JSONResponse({'agents': entries, 'total': len(entries)})
                try:
                    body = await request.json() if request.method in ('POST', 'PATCH', 'PUT') else {}
                except (ValueError, UnicodeDecodeError):
                    raise HTTPException(400, '请求必须包含有效的 JSON。')
                body = body or {}
                if not isinstance(body, dict):
                    raise HTTPException(400, '请求必须是 JSON 对象。')
                agent = request.query_params.get('agent_id') or body.get('agent_id')
                if agent:
                    allowed = grant_for(username, agent)
                    if (not path.startswith('/schedule') and
                            (body.get('workspace_id') or body.get('cwd') or body.get('permission_mode'))):
                        raise HTTPException(403, '工作区与运行权限由管理员维护。')
                    for key in ('chat_model_config', 'fallback_chat_model_config', 'tts_model_config'):
                        cfg = body.get(key)
                        if cfg and cfg.get('credential_id') not in allowed['credentials']:
                            raise HTTPException(403, '此智能体未获准使用该模型凭据。')
                    kb = body.get('knowledge_config')
                    if kb and not set(kb.get('knowledge_base_ids', [])) <= set(allowed['knowledge']):
                        raise HTTPException(403, '此智能体未获准使用该知识库。')
                allowed_read = path in ('/health', '/agent', '/model', '/credential', '/credential/schemas',
                    '/tts-model', '/knowledge_bases', '/sessions', '/knowledge_bases/middleware/parameters_schema')
                allowed_read |= path.startswith('/sessions/') and bool(agent)
                allowed_read |= path.startswith('/model/') or path.startswith('/tts_model/')
                allowed_read |= path == '/schedule' or path.startswith('/schedule/')
                allowed_write = (path == '/chat' or path == '/sessions' or
                                 path.startswith('/sessions/')) and bool(agent)
                allowed_write |= path == '/schedule' or path.startswith('/schedule/')
                if not ((request.method == 'GET' and allowed_read) or
                        (request.method in ('POST', 'PATCH', 'DELETE') and allowed_write)):
                    raise HTTPException(403, '此操作仅管理员可用。')
                if path == '/chat' and request.method == 'POST':
                    sid = body.get('session_id')
                    session = await app.state.storage.get_session(username, agent, sid)
                    if session is None:
                        raise HTTPException(404, '会话不存在。')
                    cfg = session.config
                    for model in (cfg.chat_model_config, cfg.fallback_chat_model_config, cfg.tts_model_config):
                        if model and model.credential_id not in allowed['credentials']:
                            raise HTTPException(403, '模型权限已变更，请联系管理员。')
                    if cfg.knowledge_config and not set(cfg.knowledge_config.knowledge_base_ids) <= set(allowed['knowledge']):
                        raise HTTPException(403, '知识库权限已变更，请新建会话。')
                    # A revoked resource may exist in old context. Never reuse
                    # that context after an authorization change.
                    stamp = hashlib.sha256(json.dumps(allowed, sort_keys=True).encode()).hexdigest()
                    key = selection_key(username, agent, sid)
                    with LOCK:
                        data = load()
                        if key in data['runs'] and data['runs'][key] != stamp:
                            raise HTTPException(409, '授权已更新，请新建会话后继续。')
                        data['runs'][key] = stamp
                        save(data)
                return await call_next(request)
            except HTTPException as exc:
                return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)

    app.add_middleware(PortalGate)
