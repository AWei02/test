"""Administrator-only, read-only project channel session inspection."""
import json
from fastapi import HTTPException, Request

def install_routes(router, app, require_admin):
    async def records(pid, request):
        require_admin(request)
        from portal import ADMIN, load
        from project_files import accessible
        accessible(ADMIN, pid)
        channels = {c.id: c for c in await app.state.storage.list_channels(ADMIN)}
        found = {}
        # Includes sessions created before the project was first bound.
        for cid, c in channels.items():
            if c.session.project_id == pid:
                for s in await app.state.storage.list_sessions_by_channel(ADMIN, cid):
                    found[(s.agent_id, s.id)] = s
        # Keep remaining session records discoverable after channel deletion.
        for key, project in load().get('project_sessions', {}).items():
            owner, aid, sid = json.loads(key)
            if owner == ADMIN and project == pid:
                s = await app.state.storage.get_session(owner, aid, sid)
                if s and getattr(s.origin, 'channel_id', None):
                    found[(aid, sid)] = s
        return channels, found

    @router.get('/projects/{pid}/channel-records')
    async def list_records(pid: str, request: Request):
        channels, found = await records(pid, request)
        result = []
        for s in found.values():
            cid = s.origin.channel_id
            c = channels.get(cid)
            result.append({'session_id':s.id,'agent_id':s.agent_id,'name':s.config.name,
                'channel_id':cid,'channel_name':(c.name or c.channel_type) if c else '已删除频道',
                'chat_name':getattr(s.origin,'chat_name',None),'chat_id':getattr(s.origin,'chat_id',None),
                'channel_user_id':getattr(s.origin,'channel_user_id',None),
                'created_at':s.created_at.isoformat(),'updated_at':s.updated_at.isoformat()})
        return sorted(result, key=lambda r:r['updated_at'], reverse=True)

    @router.get('/projects/{pid}/channel-records/{agent_id}/{sid}/messages')
    async def messages(pid: str, agent_id: str, sid: str, request: Request, before: str | None = None):
        _, found = await records(pid, request)
        if (agent_id, sid) not in found:
            raise HTTPException(404, '该项目中不存在此频道会话')
        from portal import ADMIN
        rows, more = await app.state.storage.list_messages(ADMIN, sid, limit=100, before=before)
        return {'messages': rows, 'has_more':more}
