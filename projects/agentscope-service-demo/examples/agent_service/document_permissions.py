"""Knowledge document permissions and their management endpoints."""
from datetime import datetime
from typing import Literal
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, model_validator


class DocumentPermissions(BaseModel):
    access_mode: Literal['inherit', 'private', 'custom'] = 'inherit'
    access_users: list[str] = Field(default_factory=list, max_length=500)
    access_roles: list[str] = Field(default_factory=list, max_length=500)

    @model_validator(mode='after')
    def validate_selection(self):
        if self.access_mode == 'custom' and not (self.access_users or self.access_roles):
            raise ValueError('自定义范围至少选择一个用户或角色')
        if self.access_mode != 'custom':
            self.access_users, self.access_roles = [], []
        return self


class Defaults(BaseModel):
    access_mode: Literal['inherit', 'private'] = 'inherit'


def install_routes(router, app, require_admin):
    from portal import load, save, LOCK, ADMIN

    @router.get('/document-permissions/options')
    async def options(request: Request):
        require_admin(request)
        data = load()
        return {'users': [u['username'] for u in data['users'] if u['enabled']], 'roles': data['roles']}

    @router.get('/knowledge-permissions/{kb_id}')
    async def settings(kb_id: str, request: Request):
        require_admin(request)
        await app.state.resource_access_service.resolve_knowledge_base(ADMIN, kb_id)
        data = load()
        return {'access_mode': data.get('knowledge_defaults', {}).get(kb_id, 'inherit'),
                'history': data.get('document_permission_history', {}).get(kb_id, [])[-50:][::-1]}

    @router.patch('/knowledge-permissions/{kb_id}')
    async def defaults(kb_id: str, body: Defaults, request: Request):
        require_admin(request)
        await app.state.resource_access_service.resolve_knowledge_base(ADMIN, kb_id)
        with LOCK:
            data = load()
            data.setdefault('knowledge_defaults', {})[kb_id] = body.access_mode
            save(data)
        return body

    @router.patch('/document-permissions/{kb_id}/{document_id}')
    async def update(kb_id: str, document_id: str, body: DocumentPermissions, request: Request):
        require_admin(request)
        kb = await app.state.resource_access_service.resolve_knowledge_base(ADMIN, kb_id)
        doc = await app.state.storage.get_knowledge_document(kb.user_id, kb_id, document_id)
        if doc is None:
            raise HTTPException(404, '文件不存在')
        if doc.status not in ('ready', 'error', 'awaiting_parse_confirmation', 'awaiting_chunk_confirmation'):
            raise HTTPException(409, '文件正在处理，请完成后再修改权限')
        data = load()
        if not set(body.access_users) <= {u['username'] for u in data['users']} or not set(body.access_roles) <= set(data['roles']):
            raise HTTPException(400, '选择的用户或角色已不存在，请重新选择')
        before = {k: getattr(doc.data, k) for k in DocumentPermissions.model_fields}
        doc.data = doc.data.model_copy(update=body.model_dump())
        doc.updated_at = datetime.now()
        await app.state.storage.upsert_knowledge_document(kb.user_id, doc)
        with LOCK:
            data = load()
            history = data.setdefault('document_permission_history', {}).setdefault(kb_id, [])
            history.append({'document_id': doc.id, 'filename': doc.data.filename,
                            'actor': ADMIN, 'at': doc.updated_at.isoformat(),
                            'before': before, 'after': body.model_dump()})
            data['document_permission_history'][kb_id] = history[-500:]
            save(data)
        return {'ok': True}
