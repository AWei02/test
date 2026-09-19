"""Private projects, session membership and recoverable shared file operations."""
import asyncio
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
from uuid import uuid4
from fastapi import HTTPException, Request, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel, Field

from data_paths import PROJECTS
ROOT = PROJECTS
LOCKS = defaultdict(asyncio.Lock)


def member_key(user, agent, session):
    return json.dumps([user, agent, session])


def owned(user, project_id):
    from portal import load
    project = load().get('projects', {}).get(project_id)
    if not project or project.get('deleted') or project['owner'] != user:
        raise HTTPException(404, '项目不存在')
    return project


def accessible(user, project_id):
    """Sharing grants the directory only; never another user's sessions."""
    from portal import load, user_for, grant_for, ADMIN
    data = load()
    user_for(user, data)
    project = data.get('projects', {}).get(project_id)
    if project and project.get('deleted'):
        raise HTTPException(404, '项目已删除')
    if project and project['owner'] == user:
        return project
    if project and project.get('shared') and project.get('agent_id'):
        try:
            if user != ADMIN:
                grant_for(user, project['agent_id'], data)
            return project
        except HTTPException:
            pass
    raise HTTPException(404, '项目不存在或当前无访问权限')


def membership(user, agent, session):
    from portal import load
    pid = load().get('project_sessions', {}).get(member_key(user, agent, session))
    if not pid:
        return None
    project = accessible(user, pid)
    if project['owner'] != user and project.get('agent_id') != agent:
        raise HTTPException(403, '该会话智能体不符合项目共享范围')
    return project


def bind_schedule_session(user, agent, session, project_id):
    """Pin a new schedule session without changing historical bindings."""
    from portal import LOCK, load, save

    project = accessible(user, project_id)
    if project.get('agent_id') != agent:
        raise HTTPException(403, '项目和智能体不匹配')
    key = member_key(user, agent, session)
    with LOCK:
        data = load()
        data.setdefault('project_sessions', {}).setdefault(key, project_id)
        save(data)
    return project


def project_directory(user, pid):
    accessible(user, pid)
    directory = ROOT / pid / 'files'
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def filename(name):
    if not name or name in ('.', '..') or len(name) > 180 or any(c in name for c in ('/', '\\', '\x00')):
        raise HTTPException(400, '文件名无效；目前文件管理采用平铺目录')
    return name


def read_file(directory, name):
    try:
        fd = os.open(directory / filename(name), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise HTTPException(400, '仅允许普通文件')
            data = source.read(20 * 1024 * 1024 + 1)
            if len(data) > 20 * 1024 * 1024:
                raise HTTPException(400, '单文件最大 20MB')
            return data
    except OSError:
        raise HTTPException(404, '文件不存在或不允许访问链接') from None


def snapshot(directory):
    """Back up root-level files before tools or users modify the workspace."""
    from file_catalog import sync
    sync(directory)
    history = ROOT / 'history' / hashlib.sha256(str(directory.resolve()).encode()).hexdigest()
    files = [p for p in directory.iterdir() if p.is_file() and not p.is_symlink()]
    if len(files) > 250 or sum(p.stat().st_size for p in files) > 100 * 1024 * 1024:
        raise HTTPException(400, '文件区超过 250 个文件或 100MB，请先整理')
    version = uuid4().hex
    dest = history / version
    dest.mkdir(parents=True)
    for path in files:
        (dest / path.name).write_bytes(read_file(directory, path.name))
    return version


def write_file(directory, name, data):
    name = filename(name)
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(400, '单文件最大 20MB')
    temp = directory / ('.upload-' + uuid4().hex)
    try:
        temp.write_bytes(data)
        os.replace(temp, directory / name)
    finally:
        temp.unlink(missing_ok=True)


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default='', max_length=4000)
    agent_id: str = ''
    shared: bool = False


class BindInput(BaseModel):
    agent_id: str
    session_id: str


class DeleteProjectInput(BaseModel):
    confirmed: bool = False

class SessionPinInput(BindInput):
    pinned: bool


class FileChange(BaseModel):
    name: str
    new_name: str = ''
    version: str = ''
    confirmed: bool = False


from agentscope.tool import ToolBase, ToolChunk
from agentscope.message import TextBlock, ToolResultState


class ProjectFiles(ToolBase):
    name = 'ProjectFiles'
    description = '操作当前项目（或普通对话）的文件：list 列出文件，read 读取 UTF-8 文本，write 写入文本，delete 删除，rename 重命名。文件共享范围由会话归属决定，不允许访问其他项目。修改同一文件保留来源和历史版本；另存副本创建新文件，并用 source_names 记录来源。不明确是否覆盖时优先创建副本。二进制分析请使用已授权技能，路径为 /work/文件名。'
    is_concurrency_safe = False
    is_read_only = False
    input_schema = {'type': 'object', 'properties': {
        'action': {'type': 'string', 'enum': ['list', 'read', 'write', 'delete', 'rename']},
        'name': {'type': 'string'}, 'content': {'type': 'string', 'maxLength': 100000},
        'new_name': {'type': 'string'},
        'source_names': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 30, 'description': '另存或派生新文件时填写实际来源文件名；不要猜测'},
    }, 'required': ['action'], 'additionalProperties': False}

    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace

    async def check_permissions(self, tool_input, context):
        from agentscope.permission import PermissionDecision, PermissionBehavior
        return PermissionDecision(behavior=PermissionBehavior.ALLOW, message='仅当前会话文件区，修改会保留历史备份。')

    async def call(self, action, name='', content='', new_name='', source_names=None):
        from skill_packages import workdir
        from portal import user_for, grant_for, ADMIN
        try:
            ws = self.workspace
            user_for(ws.username)
            if ws.username != ADMIN:
                grant_for(ws.username, ws.agent)
            directory = workdir(ws.username, ws.agent, ws.session)
            async with LOCKS[str(directory)]:
                from file_catalog import sync, source_refs, rename as catalog_rename
                source_refs(sync(directory), source_names)
                if action == 'list':
                    project = membership(ws.username, ws.agent, ws.session)
                    text = json.dumps({'scope': project['name'] if project else '普通对话',
                        'description': project.get('description', '') if project else '',
                        'files': [p.name for p in directory.iterdir() if p.is_file() and not p.is_symlink()]}, ensure_ascii=False)
                elif action == 'read':
                    text = read_file(directory, name.removeprefix('/work/')).decode('utf-8-sig')[:100000]
                elif action in ('write', 'delete', 'rename'):
                    name = filename(name.removeprefix('/work/'))
                    if action != 'write':
                        read_file(directory, name)
                    if action == 'rename':
                        new_name = filename(new_name.removeprefix('/work/'))
                        if (directory / new_name).exists():
                            raise HTTPException(409, '目标文件已存在')
                    version = snapshot(directory)
                    if action == 'write':
                        write_file(directory, name, content.encode('utf-8'))
                    elif action == 'delete':
                        (directory / name).unlink()
                    else:
                        (directory / name).rename(directory / new_name)
                    if action == 'rename':
                        catalog_rename(directory, name, new_name, 'AI')
                    sync(directory, actor='AI', origin='generated', sources=source_names)
                    text = '操作完成，修改前版本：' + version
                else:
                    raise HTTPException(400, '未知文件操作')
            return ToolChunk(content=[TextBlock(text=text)], state=ToolResultState.SUCCESS)
        except (HTTPException, OSError, UnicodeError) as error:
            return ToolChunk(content=[TextBlock(text=str(getattr(error, 'detail', error)))], state=ToolResultState.ERROR)


def install_routes(router, app):
    def user(request):
        from portal import user_for
        username = request.headers.get('x-user-id', '')
        user_for(username)
        return username

    @router.get('/session-pins')
    async def session_pins(request: Request):
        from portal import load
        username = user(request)
        return [{'agent_id': a, 'session_id': s} for key, pinned in load().get('session_pins', {}).items()
                for u, a, s in [json.loads(key)] if u == username and pinned]

    @router.post('/session-pins')
    async def pin_session(body: SessionPinInput, request: Request):
        from portal import load, save, LOCK
        username = user(request)
        if not await app.state.storage.get_session(username, body.agent_id, body.session_id):
            raise HTTPException(404, '会话不存在')
        with LOCK:
            data = load()
            pins = data.setdefault('session_pins', {})
            key = member_key(username, body.agent_id, body.session_id)
            if body.pinned: pins[key] = True
            else: pins.pop(key, None)
            save(data)
        return {'ok': True}

    @router.get('/projects')
    async def list_projects(request: Request):
        from portal import load
        username = user(request)
        data = load()
        projects = []
        for pid in data.get('projects', {}):
            try:
                p = accessible(username, pid)
                projects.append({**p, 'is_owner': p['owner'] == username})
            except HTTPException:
                continue
        bindings = []
        for key, pid in data.get('project_sessions', {}).items():
            owner, agent, sid = json.loads(key)
            if owner == username:
                record = await app.state.storage.get_session(owner, agent, sid)
                if record:
                    bindings.append({'agent_id': agent, 'session_id': sid, 'project_id': pid,
                                     'name': record.config.name, 'created_at': record.created_at.isoformat()})
        return {'projects': projects, 'bindings': bindings}

    async def validate_agent(username, agent_id):
        from portal import ADMIN, grant_for
        if username != ADMIN:
            grant_for(username, agent_id)
        if not await app.state.storage.get_agent(ADMIN, agent_id):
            raise HTTPException(400, '请选择有效的智能体')

    @router.post('/projects')
    async def create_project(body: ProjectInput, request: Request):
        from portal import load, save, LOCK
        username = user(request)
        if body.shared and not body.agent_id:
            raise HTTPException(400, '共享项目必须指定智能体')
        if body.agent_id:
            await validate_agent(username, body.agent_id)
        project = {'id': uuid4().hex, 'owner': username, **body.model_dump()}
        with LOCK:
            data = load()
            data.setdefault('projects', {})[project['id']] = project
            save(data)
        return project

    @router.put('/projects/{pid}')
    async def edit_project(pid: str, body: ProjectInput, request: Request):
        from portal import load, save, LOCK
        username = user(request)
        project = owned(username, pid)
        # Old clients may omit the new fields; preserve settings on ordinary edits.
        changes = body.model_dump(exclude_unset=True)
        candidate = {**project, **changes}
        if project.get('agent_id') and candidate.get('agent_id') != project['agent_id']:
            raise HTTPException(409, '项目智能体已固定，如需其他智能体请新建项目')
        if candidate.get('shared') and not candidate.get('agent_id'):
            raise HTTPException(400, '共享项目必须指定智能体')
        if candidate.get('agent_id') and (candidate.get('shared') or candidate.get('agent_id') != project.get('agent_id')):
            await validate_agent(username, candidate['agent_id'])
        if candidate.get('agent_id') != project.get('agent_id'):
            # Existing project paths stay pinned to their original sharing scope.
            for key, value in load().get('project_sessions', {}).items():
                if value == pid:
                    owner, agent, sid = json.loads(key)
                    if agent != candidate.get('agent_id') and await app.state.storage.get_session(owner, agent, sid):
                        raise HTTPException(409, '项目已有其他智能体的会话，请保持原智能体或新建项目')
        with LOCK:
            data = load()
            owned(username, pid)
            data['projects'][pid].update(changes)
            save(data)
        return data['projects'][pid]

    @router.post('/projects/{pid}/delete')
    async def delete_project(pid: str, body: DeleteProjectInput, request: Request):
        from portal import load, save, LOCK
        username = user(request)
        owned(username, pid)
        if not body.confirmed:
            raise HTTPException(400, '请先确认删除项目')
        directory = ROOT / pid / 'files'
        async with LOCKS[str(directory)]:
            with LOCK:
                owned(username, pid)
                data = load()
                data['projects'][pid]['deleted'] = True
                data['projects'][pid]['shared'] = False
                save(data)
        return {'ok': True}

    @router.post('/projects/{pid}/sessions')
    async def bind_session(pid: str, body: BindInput, request: Request):
        from portal import load, save, LOCK, ADMIN, grant_for
        username = user(request)
        project = accessible(username, pid)
        if project.get('agent_id') and project['agent_id'] != body.agent_id:
            raise HTTPException(403, '请使用项目指定的智能体')
        if username != ADMIN:
            grant_for(username, body.agent_id)
        # Only a freshly created, unused session may be attached; never migrate files silently.
        from skill_packages import WORK
        key = member_key(username, body.agent_id, body.session_id)
        old = load().get('project_sessions', {}).get(key)
        if old:
            if old == pid:
                return {'ok': True}
            raise HTTPException(409, '会话已属于其他项目')
        legacy = WORK / hashlib.sha256(json.dumps([username, body.agent_id, body.session_id]).encode()).hexdigest()
        if legacy.exists() and any(legacy.iterdir()):
            raise HTTPException(409, '会话已有独立文件，请从项目中新建会话')
        from agentscope.app.message_bus import MessageBusKeys
        lock_key = MessageBusKeys.session_lock(body.session_id)
        if await app.state.message_bus.is_locked(lock_key):
            raise HTTPException(409, '会话正在运行，请从项目中新建会话')
        async with app.state.message_bus.acquire_lock(lock_key):
            session = await app.state.storage.get_session(username, body.agent_id, body.session_id)
            if session is None:
                raise HTTPException(404, '会话不存在')
            if session.state.context or session.state.summary:
                raise HTTPException(409, '已有对话记录，请从项目中新建会话')
            with LOCK:
                data = load()
                old = data.get('project_sessions', {}).get(key)
                if old and old != pid:
                    raise HTTPException(409, '会话已属于其他项目')
                data.setdefault('project_sessions', {})[key] = pid
                save(data)
        return {'ok': True}

    @router.get('/session-project/{agent}/{sid}')
    async def session_project(agent: str, sid: str, request: Request):
        username = user(request)
        if not await app.state.storage.get_session(username, agent, sid):
            raise HTTPException(404, '会话不存在')
        return {'project': membership(username, agent, sid)}

    @router.get('/projects/{pid}/sessions')
    async def project_sessions(pid: str, request: Request):
        from portal import load
        username = user(request)
        accessible(username, pid)
        result = []
        for key, value in load().get('project_sessions', {}).items():
            owner, agent, sid = json.loads(key)
            if owner == username and value == pid:
                record = await app.state.storage.get_session(owner, agent, sid)
                if record:
                    result.append({'agent_id': agent, 'session_id': sid, 'name': record.config.name})
        return result

    @router.get('/projects/{pid}/files')
    async def files(pid: str, request: Request):
        directory = project_directory(user(request), pid)
        async with LOCKS[str(directory)]:
            return {'files': [{'name': p.name, 'size': p.stat().st_size} for p in directory.iterdir() if p.is_file() and not p.is_symlink()]}

    @router.post('/projects/{pid}/files')
    async def upload(pid: str, request: Request, file: UploadFile = File(...)):
        directory = project_directory(user(request), pid)
        name = filename(file.filename or '')
        raw = await file.read(20 * 1024 * 1024 + 1)
        if len(raw) > 20 * 1024 * 1024:
            raise HTTPException(400, '单文件最大 20MB')
        async with LOCKS[str(directory)]:
            if (directory / name).exists():
                raise HTTPException(409, '同名文件已存在，请先重命名或删除（可恢复）')
            snapshot(directory)
            write_file(directory, name, raw)
            from file_catalog import sync
            sync(directory, actor=user(request), origin='uploaded', names=[name])
        return {'ok': True}

    @router.get('/projects/{pid}/files/{name}')
    async def download(pid: str, name: str, request: Request):
        directory = project_directory(user(request), pid)
        async with LOCKS[str(directory)]:
            return Response(read_file(directory, name), media_type='application/octet-stream')

    @router.post('/projects/{pid}/file-actions/{action}')
    async def change_file(pid: str, action: str, body: FileChange, request: Request):
        directory = project_directory(user(request), pid)
        name = filename(body.name)
        async with LOCKS[str(directory)]:
            if action == 'restore':
                if len(body.version) != 32 or any(c not in '0123456789abcdef' for c in body.version):
                    raise HTTPException(400, '版本无效')
                history = ROOT / 'history' / hashlib.sha256(str(directory.resolve()).encode()).hexdigest()
                raw = read_file(history / body.version, name)
                snapshot(directory)
                write_file(directory, name, raw)
            elif action in ('delete', 'rename'):
                read_file(directory, name)
                if action == 'rename':
                    new = filename(body.new_name)
                    if (directory / new).exists():
                        raise HTTPException(409, '目标文件已存在')
                snapshot(directory)
                if action == 'delete':
                    (directory / name).unlink()
                else:
                    (directory / name).rename(directory / new)
            else:
                raise HTTPException(400, '未知操作')
            from file_catalog import sync, rename as catalog_rename
            if action == 'rename':
                catalog_rename(directory, name, new, user(request))
            sync(directory, actor=user(request))
        return {'ok': True}

    @router.post('/projects/{pid}/history/delete')
    async def delete_history(pid: str, body: FileChange, request: Request):
        username = user(request)
        owned(username, pid)
        if not body.confirmed:
            raise HTTPException(400, '请先确认彻底删除历史版本')
        if len(body.version) != 32 or any(c not in '0123456789abcdef' for c in body.version):
            raise HTTPException(400, '版本无效')
        name = filename(body.name)
        directory = project_directory(username, pid)
        history = ROOT / 'history' / hashlib.sha256(str(directory.resolve()).encode()).hexdigest()
        async with LOCKS[str(directory)]:
            owned(username, pid)
            version = history / body.version
            read_file(version, name)
            (version / name).unlink()
            if not any(version.iterdir()):
                version.rmdir()
        return {'ok': True}

    @router.get('/projects/{pid}/history')
    async def history(pid: str, request: Request):
        directory = project_directory(user(request), pid)
        root = ROOT / 'history' / hashlib.sha256(str(directory.resolve()).encode()).hexdigest()
        async with LOCKS[str(directory)]:
            return [{'version': v.name, 'time': v.stat().st_mtime, 'name': p.name}
                    for v in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
                    for p in v.iterdir() if p.is_file()] if root.exists() else []
