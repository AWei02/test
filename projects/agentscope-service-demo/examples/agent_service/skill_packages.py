"""Admin ZIP installation and Docker-contained execution of selected skills."""
import asyncio
import io
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
import zipfile

import yaml
from fastapi import HTTPException, Request, UploadFile, File
from agentscope.app.storage import SkillRecord
from agentscope.skill import Skill
from agentscope.tool import ToolBase, ToolChunk
from agentscope.message import TextBlock, ToolResultState

from data_paths import SKILLS, SESSION_FILES
ROOT = SKILLS
WORK = SESSION_FILES
BASE_IMAGE = 'python:3.12-slim'
BUILD_LOCK = asyncio.Lock()


def workdir(username, agent, session):
    from project_files import membership, project_directory
    project = membership(username, agent, session)
    if project:
        return project_directory(username, project['id'])
    key = hashlib.sha256(json.dumps([username, agent, session]).encode()).hexdigest()
    directory = WORK / key
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def extract_package(raw, destination):
    """Reject traversal, links, duplicate paths, ZIP bombs, and ambiguous roots."""
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError('ZIP 不能超过 20MB')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        items = archive.infolist()
        if len(items) > 2000 or sum(i.file_size for i in items) > 100 * 1024 * 1024:
            raise ValueError('解压后不能超过 100MB 或 2000 个文件')
        seen = set()
        for item in items:
            path = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            if (path.is_absolute() or '..' in path.parts or '\\' in item.filename
                    or ':' in item.filename or not path.parts
                    or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
                    or item.flag_bits & 1 or item.filename in seen):
                raise ValueError('ZIP 含不安全路径、链接、特殊文件、加密或重复文件')
            seen.add(item.filename)
        for item in items:
            target = destination.joinpath(*PurePosixPath(item.filename).parts)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as src, target.open('wb') as dst:
                    shutil.copyfileobj(src, dst)
    roots = [destination] if (destination / 'SKILL.md').is_file() else [
        p for p in destination.iterdir() if p.is_dir() and (p / 'SKILL.md').is_file()]
    if len(roots) != 1:
        raise ValueError('ZIP 根目录或唯一顶层目录必须包含 SKILL.md')
    root = roots[0]
    markdown = (root / 'SKILL.md').read_text('utf-8')
    if len(markdown) > 200000 or not markdown.startswith('---\n'):
        raise ValueError('SKILL.md 必须包含 YAML 头部 name、description')
    meta = yaml.safe_load(markdown.split('---', 2)[1])
    if not isinstance(meta, dict) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', str(meta.get('name', ''))):
        raise ValueError('技能 name 只能包含小写字母、数字、连字符，最多 64 字符')
    if not isinstance(meta.get('description'), str) or not meta['description'].strip():
        raise ValueError('请填写 description')
    return root, meta, markdown


def build_image(root, tag):
    # Only this extracted package is sent to Docker; never include server secrets.
    runtime = json.loads((root / 'runtime.json').read_text()) if (root / 'runtime.json').exists() else {}
    if not isinstance(runtime, dict):
        raise ValueError('runtime.json 必须是 JSON 对象')
    packages = runtime.get('apt_packages', [])
    if not isinstance(packages, list) or len(packages) > 40 or not all(
        isinstance(p, str) and re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', p) for p in packages
    ):
        raise ValueError('runtime.json 的 apt_packages 必须是系统包名称数组')
    dockerfile = f'FROM {BASE_IMAGE}\n'
    if packages:
        dockerfile += 'RUN apt-get update && apt-get install -y --no-install-recommends ' + ' '.join(packages) + ' && rm -rf /var/lib/apt/lists/*\n'
    dockerfile += 'COPY . /skill\n'
    if (root / 'requirements.txt').exists():
        dockerfile += 'RUN python -m pip install --no-cache-dir -r /skill/requirements.txt\n'
    dockerfile += 'ENV PYTHONDONTWRITEBYTECODE=1 HOME=/tmp\nWORKDIR /work\n'
    result = subprocess.run(['docker', 'build', '--network=default', '-t', tag, '-f', '-', str(root)],
                            input=dockerfile, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=300)
    if result.returncode:
        raise ValueError('依赖构建失败，请检查 requirements.txt、runtime.json 和 Docker 网络。')


def package_skill(record):
    root = ROOT / record.id / 'content'
    if not (root / 'SKILL.md').is_file():
        return None
    manifest = json.loads((root.parent / 'manifest.json').read_text())
    files = '\n'.join(str(p.relative_to(root)) for p in root.rglob('*') if p.is_file())
    instructions = (record.markdown + '\n\n执行环境：使用 RunSkill 工具，skill_id=' + record.id
        + '。脚本路径相对技能根目录；args 是参数数组。action=read 可读取说明/模板文本，action=run 执行 .py/.sh。'
        + '完整技能文件在容器 /skill（只读），工作目录 /work（同一会话持久保存），可写临时目录 /tmp。'
        + '无网络、无宿主机文件/凭据。不要使用宿主机 Bash 执行本技能。\n文件清单：\n' + files)
    return Skill(name=record.name, description=record.description, dir='/skill', markdown=instructions, updated_at=0), manifest


class RunSkill(ToolBase):
    name = 'RunSkill'
    description = '运行已授权且当前选中的完整技能包脚本，或读取技能包中的文本文件。Python/Shell 在独立 Docker 容器运行，依赖已安装。'
    is_concurrency_safe = False
    is_read_only = False
    input_schema = {'type': 'object', 'properties': {
        'skill_id': {'type': 'string'}, 'path': {'type': 'string'},
        'action': {'type': 'string', 'enum': ['run', 'read']},
        'args': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 100},
        'source_names': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 30, 'description': '本次脚本实际使用的输入文件名，用于关联生成文件'},
    }, 'required': ['skill_id', 'path', 'action'], 'additionalProperties': False}

    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace

    async def check_permissions(self, tool_input, context):
        from agentscope.permission import PermissionDecision, PermissionBehavior
        allowed = tool_input.get('skill_id') in self.workspace.selected('skills')
        return PermissionDecision(behavior=PermissionBehavior.ALLOW if allowed else PermissionBehavior.DENY,
                                  message='技能授权在执行时再次校验；仅在隔离容器中运行。')

    async def call(self, skill_id, path, action, args=None, source_names=None):
        try:
            if skill_id not in self.workspace.selected('skills'):
                raise ValueError('技能未授权或未选中')
            from portal import ADMIN
            record = await self.workspace.storage.get_skill(ADMIN, skill_id)
            if not record or not record.enabled or not package_skill(record):
                raise ValueError('完整技能包不存在或已停用')
            root = ROOT / record.id / 'content'
            relative = PurePosixPath(path)
            if relative.is_absolute() or '..' in relative.parts or '\\' in path:
                raise ValueError('只允许技能目录内的相对文件路径')
            target = root.joinpath(*relative.parts)
            if not target.is_file():
                raise ValueError('技能文件不存在')
            if action == 'read':
                text = target.read_bytes()[:32000].decode('utf-8', errors='replace')
            elif action == 'run':
                if target.suffix not in ('.py', '.sh'):
                    raise ValueError('执行入口仅支持 .py 和 .sh；脚本可调用容器中已安装的其他程序')
                if not isinstance(args or [], list) or len(args or []) > 100 or not all(isinstance(a, str) and len(a) < 16000 for a in args or []):
                    raise ValueError('脚本参数无效')
                manifest = package_skill(record)[1]
                text, successful = await self.execute(manifest['image'], path, args or [], source_names)
                return ToolChunk(content=[TextBlock(text=text)],
                    state=ToolResultState.SUCCESS if successful else ToolResultState.ERROR)
            else:
                raise ValueError('不支持的操作')
            return ToolChunk(content=[TextBlock(text=text)], state=ToolResultState.SUCCESS)
        except (ValueError, OSError, HTTPException) as error:
            return ToolChunk(content=[TextBlock(text=str(getattr(error, 'detail', error)))], state=ToolResultState.ERROR)

    async def execute(self, image, path, args, source_names=None):
        from project_files import LOCKS, snapshot
        directory = workdir(self.workspace.username, self.workspace.agent, self.workspace.session)
        async with LOCKS[str(directory)]:
            from file_catalog import sync, source_refs
            source_refs(sync(directory), source_names)
            snapshot(directory)
            try:
                return await self._execute(image, path, args)
            finally:
                sync(directory, actor='AI · 技能', origin='generated', sources=source_names)

    async def _execute(self, image, path, args):
        # Bind only the dedicated session output directory, never the host workspace.
        output = workdir(self.workspace.username, self.workspace.agent, self.workspace.session)
        name = 'portal-skill-' + uuid.uuid4().hex
        command = ['docker', 'run', '--rm', '--name', name, '--network=none', '--read-only',
            '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=64',
            '--memory=512m', '--cpus=1', '--ulimit', 'fsize=67108864:67108864',
            '--user', f'{os.getuid()}:{os.getgid()}', '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m',
            '--mount', f'type=bind,src={output.resolve()},dst=/work',
            image, 'python' if path.endswith('.py') else 'bash', '/skill/' + path, *args]
        process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        chunks, size = [], 0
        async def read():
            nonlocal size
            while block := await process.stdout.read(4096):
                if size < 32000:
                    chunks.append(block[:32000-size])
                    size += len(chunks[-1])
            await process.wait()
        try:
            await asyncio.wait_for(read(), 60)
            return (f'exit_code={process.returncode}\n' + b''.join(chunks).decode('utf-8', errors='replace') + '\n输出文件保存在本会话技能文件区，可通过页面下载。', process.returncode == 0)
        except asyncio.TimeoutError:
            return '脚本超过 60 秒限制，容器已停止。', False
        finally:
            cleanup = await asyncio.create_subprocess_exec('docker', 'rm', '-f', name, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await cleanup.wait()
            await process.wait()


def install_routes(router, app, require_admin):
    from fastapi.responses import Response

    async def session_directory(request, agent_id, session_id):
        from portal import ADMIN, grant_for, user_for
        username = request.headers.get('x-user-id', '')
        user_for(username)
        if username != ADMIN:
            grant_for(username, agent_id)
        session = await app.state.storage.get_session(username, agent_id, session_id)
        if session is None:
            raise HTTPException(404, '会话不存在')
        return workdir(username, agent_id, session_id)

    @router.get('/skill-files/{agent_id}/{session_id}')
    async def list_files(agent_id: str, session_id: str, request: Request):
        directory = await session_directory(request, agent_id, session_id)
        return {'files': [p.name for p in directory.iterdir() if p.is_file() and not p.is_symlink()][:200]}

    @router.get('/skill-files/{agent_id}/{session_id}/{filename}')
    async def download_file(agent_id: str, session_id: str, filename: str, request: Request):
        directory = await session_directory(request, agent_id, session_id)
        if filename in ('.', '..') or '/' in filename or '\\' in filename:
            raise HTTPException(400, '文件名无效')
        try:
            fd = os.open(directory / filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise HTTPException(400, '仅支持普通文件')
                data = stream.read(20 * 1024 * 1024 + 1)
                if len(data) > 20 * 1024 * 1024:
                    raise HTTPException(400, '单文件下载上限 20MB')
            return Response(content=data, media_type='application/octet-stream')
        except OSError:
            raise HTTPException(404, '文件不存在或不允许访问链接') from None

    @router.delete('/skill-files/{agent_id}/{session_id}/{filename}')
    async def delete_input(agent_id: str, session_id: str, filename: str, request: Request, confirmed: bool = False):
        directory = await session_directory(request, agent_id, session_id)
        from project_files import LOCKS, snapshot, read_file, membership
        if membership(request.headers.get('x-user-id', ''), agent_id, session_id):
            raise HTTPException(409, '请在项目文件页面删除共享文件')
        if not confirmed:
            raise HTTPException(400, '请先确认删除文件')
        async with LOCKS[str(directory)]:
            await session_directory(request, agent_id, session_id)
            read_file(directory, filename)
            version = snapshot(directory)
            (directory / filename).unlink()
            from file_catalog import sync
            sync(directory, actor=request.headers.get('x-user-id', ''))
        return {'ok': True, 'backup_version': version}

    @router.post('/skill-files/{agent_id}/{session_id}')
    async def upload_input(agent_id: str, session_id: str, request: Request, file: UploadFile = File(...)):
        directory = await session_directory(request, agent_id, session_id)
        from project_files import membership
        if membership(request.headers.get('x-user-id', ''), agent_id, session_id):
            raise HTTPException(409, '项目会话请通过项目文件页面上传，以应用文件锁和历史备份')
        name = file.filename or ''
        if name in ('', '.', '..') or '/' in name or '\\' in name or len(name) > 180:
            raise HTTPException(400, '文件名无效')
        data = await file.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(400, '输入文件上限 20MB')
        from project_files import LOCKS
        from file_catalog import sync
        async with LOCKS[str(directory)]:
            await session_directory(request, agent_id, session_id)
            sync(directory)
            try:
                fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data)
            except FileExistsError:
                raise HTTPException(409, '同名文件已存在，请改名后上传') from None
            sync(directory, actor=request.headers.get('x-user-id', ''), origin='uploaded', names=[name])
        return {'name': name, 'container_path': '/work/' + name}

    @router.post('/skill-packages')
    async def upload(request: Request, file: UploadFile = File(...)):
        require_admin(request)
        raw = await file.read(20 * 1024 * 1024 + 1)
        ROOT.mkdir(parents=True, exist_ok=True)
        skill_id = uuid.uuid4().hex
        destination = ROOT / skill_id
        try:
            async with BUILD_LOCK:
                with tempfile.TemporaryDirectory(prefix='skill-import-') as temp:
                    content, meta, markdown = extract_package(raw, Path(temp))
                    from portal import ADMIN
                    if any(r.name == meta['name'] for r in await app.state.storage.list_skills(ADMIN)):
                        raise ValueError('技能名称已存在，请使用新名称或先删除旧版本')
                    tag = 'portal-skill:' + skill_id
                    await asyncio.to_thread(build_image, content, tag)
                    destination.mkdir()
                    shutil.copytree(content, destination / 'content')
                    (destination / 'manifest.json').write_text(json.dumps({'image': tag}))
                    record = SkillRecord(id=skill_id, user_id=ADMIN, name=meta['name'],
                        description=meta['description'], markdown=markdown, version=skill_id,
                        tags=['uploaded-package', 'docker-runtime'])
                    await app.state.storage.upsert_skill(ADMIN, record)
            return {'id': skill_id, 'name': meta['name'], 'status': 'ready'}
        except (ValueError, zipfile.BadZipFile, UnicodeError, yaml.YAMLError, subprocess.TimeoutExpired) as error:
            raise HTTPException(400, str(error)) from None
