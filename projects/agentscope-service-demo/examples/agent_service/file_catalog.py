"""File provenance and immutable per-file versions, outside skill mounts.
Callers hold project_files.LOCKS for every catalog operation.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field


def now():
    return datetime.now(timezone.utc).isoformat()


def catalog_root(directory):
    from project_files import ROOT
    return ROOT / 'catalog' / hashlib.sha256(str(directory.resolve()).encode()).hexdigest()


def load_index(directory):
    path = catalog_root(directory) / 'index.json'
    return json.loads(path.read_text('utf-8')) if path.exists() else {'files': {}}


def save_index(directory, data):
    root = catalog_root(directory)
    root.mkdir(parents=True, exist_ok=True)
    temp = root / (uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False), 'utf-8')
        os.replace(temp, root / 'index.json')
    finally:
        temp.unlink(missing_ok=True)


def source_refs(data, names):
    result = []
    for name in names or []:
        from project_files import filename
        name = filename(name.removeprefix('/work/'))
        entry = data['files'].get(name)
        if not entry or entry.get('deleted'):
            raise HTTPException(400, '来源文件不存在：' + name)
        result.append({'id': entry['id'], 'name': name, 'version': entry['versions'][-1]['id']})
    return result


def sync(directory, actor='来源未记录', origin='unknown', names=None, sources=None):
    from project_files import read_file
    data = load_index(directory)
    refs = source_refs(data, sources)
    seen = set()
    changed = False
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.is_symlink() or path.name.startswith('.upload-'):
            continue
        name = path.name
        seen.add(name)
        raw = read_file(directory, name)
        digest = hashlib.sha256(raw).hexdigest()
        entry = data['files'].get(name)
        targeted = names is None or name in names
        by = actor if targeted else '来源未记录'
        if entry is None:
            entry = {'id': uuid4().hex, 'name': name, 'origin': origin if targeted else 'unknown',
                     'created_at': now(), 'is_result': False, 'sources': refs if targeted else [], 'versions': []}
            data['files'][name] = entry
        if entry.get('deleted') or not entry['versions'] or entry['versions'][-1]['sha256'] != digest:
            version = {'id': uuid4().hex, 'number': len(entry['versions']) + 1,
                       'time': now(), 'actor': by, 'size': len(raw), 'sha256': digest}
            root = catalog_root(directory) / 'versions'
            root.mkdir(parents=True, exist_ok=True)
            (root / version['id']).write_bytes(raw)
            entry['versions'].append(version)
            entry.update(deleted=False, updated_at=version['time'], modified_by=by, size=len(raw))
            changed = True
    for name, entry in data['files'].items():
        if name not in seen and not entry.get('deleted'):
            entry.update(deleted=True, updated_at=now(), modified_by=actor)
            changed = True
    if changed:
        save_index(directory, data)
    return data


def rename(directory, old, new, actor):
    data = load_index(directory)
    if old in data['files']:
        entry = data['files'].pop(old)
        entry.update(name=new, updated_at=now(), modified_by=actor)
        data['files'][new] = entry
        save_index(directory, data)


def rows(data):
    return sorted([{**{k: v for k, v in entry.items() if k != 'versions'},
                    'version_count': len(entry['versions']), 'current_version': entry['versions'][-1]['id']}
                   for entry in data['files'].values() if not entry.get('deleted')],
                  key=lambda row: row['updated_at'], reverse=True)


def version_bytes(directory, name, version):
    from project_files import filename
    entry = load_index(directory)['files'].get(filename(name))
    if not entry or not any(v['id'] == version for v in entry['versions']):
        raise HTTPException(404, '历史版本不存在')
    return (catalog_root(directory) / 'versions' / version).read_bytes()


class FileAction(BaseModel):
    name: str
    action: str
    is_result: bool = False
    version: str = ''
    expected_version: str = ''
    new_name: str = ''
    confirmed: bool = False


def install_routes(router, app):
    async def resolve(scope, resource, request, agent_id):
        from portal import user_for, grant_for, ADMIN
        from project_files import project_directory
        from skill_packages import workdir
        username = request.headers.get('x-user-id', '')
        user_for(username)
        if scope == 'project':
            return project_directory(username, resource), username
        if scope != 'session' or not agent_id:
            raise HTTPException(404, '文件区不存在')
        if username != ADMIN:
            grant_for(username, agent_id)
        if await app.state.storage.get_session(username, agent_id, resource) is None:
            raise HTTPException(404, '会话不存在')
        return workdir(username, agent_id, resource), username

    @router.get('/file-catalog/{scope}/{resource}')
    async def listing(scope: str, resource: str, request: Request, agent_id: str = ''):
        from project_files import LOCKS
        directory, _ = await resolve(scope, resource, request, agent_id)
        async with LOCKS[str(directory)]:
            return {'files': rows(sync(directory))}

    @router.get('/file-catalog/{scope}/{resource}/history')
    async def history(scope: str, resource: str, request: Request, name: str, agent_id: str = ''):
        from project_files import LOCKS, filename
        directory, _ = await resolve(scope, resource, request, agent_id)
        async with LOCKS[str(directory)]:
            entry = sync(directory)['files'].get(filename(name))
            if not entry:
                raise HTTPException(404, '文件不存在')
            return {'versions': list(reversed(entry['versions']))}

    @router.get('/file-catalog/{scope}/{resource}/download')
    async def download(scope: str, resource: str, request: Request, name: str,
                       version: str = '', agent_id: str = ''):
        from project_files import LOCKS, read_file
        directory, _ = await resolve(scope, resource, request, agent_id)
        async with LOCKS[str(directory)]:
            raw = version_bytes(directory, name, version) if version else read_file(directory, name)
            return Response(raw, media_type='application/octet-stream')

    @router.post('/file-catalog/{scope}/{resource}/action')
    async def action(scope: str, resource: str, request: Request, body: FileAction, agent_id: str = ''):
        from project_files import LOCKS, filename, snapshot, write_file
        directory, username = await resolve(scope, resource, request, agent_id)
        name = filename(body.name)
        async with LOCKS[str(directory)]:
            data = sync(directory)
            entry = data['files'].get(name)
            if not entry or entry.get('deleted'):
                raise HTTPException(404, '文件不存在')
            if body.action == 'mark':
                entry['is_result'] = body.is_result
                save_index(directory, data)
            elif body.action in ('restore', 'delete', 'rename'):
                if not body.confirmed:
                    raise HTTPException(400, '请先确认操作')
                if entry['versions'][-1]['id'] != body.expected_version:
                    raise HTTPException(409, '文件已有新版本，请刷新后重试')
                if body.action == 'restore':
                    raw = version_bytes(directory, name, body.version)
                    snapshot(directory)
                    write_file(directory, name, raw)
                elif body.action == 'delete':
                    snapshot(directory)
                    (directory / name).unlink()
                else:
                    new = filename(body.new_name)
                    if (directory / new).exists() or (directory / new).is_symlink():
                        raise HTTPException(409, '同名文件已存在')
                    snapshot(directory)
                    (directory / name).rename(directory / new)
                    rename(directory, name, new, username)
                sync(directory, actor=username)
            else:
                raise HTTPException(400, '未知操作')
            return {'ok': True}
