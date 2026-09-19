"""Transfer project metadata ownership without moving files or conversations."""
from fastapi import Request, HTTPException
from pydantic import BaseModel, Field

class TransferInput(BaseModel):
    owner: str = Field(min_length=1, max_length=80)
    expected_owner: str
    confirmed: bool = False

def install_routes(router, app):
    from portal import ADMIN, LOCK, load, save, user_for, grant_for
    def project_for(username,pid,data):
        user_for(username,data)
        p=data.get('projects',{}).get(pid)
        if not p or p.get('deleted'):raise HTTPException(404,'项目不存在')
        if username!=ADMIN and p['owner']!=username:raise HTTPException(403,'仅所有者或管理员可转移项目')
        return p
    def eligible(u,p,data):
        if not u['enabled'] or u['username']==p['owner']:return False
        if u['username']==ADMIN:return True
        if not p.get('agent_id'):return False
        try:grant_for(u['username'],p['agent_id'],data);return True
        except HTTPException:return False
    @router.get('/projects/{pid}/transfer-options')
    async def options(pid:str,request:Request):
        with LOCK:
            data=load();p=project_for(request.headers.get('x-user-id',''),pid,data)
            return {'owner':p['owner'],'users':[u['username'] for u in data['users'] if eligible(u,p,data)]}
    @router.post('/projects/{pid}/transfer')
    async def transfer(pid:str,body:TransferInput,request:Request):
        if not body.confirmed:raise HTTPException(400,'请先确认转移所有权')
        from project_files import ROOT, LOCKS
        async with LOCKS[str(ROOT/pid/'files')]:
            with LOCK:
                data=load();p=project_for(request.headers.get('x-user-id',''),pid,data)
                if p['owner']!=body.expected_owner:raise HTTPException(409,'项目所有者已变更，请刷新后重试')
                target=next((u for u in data['users'] if u['username']==body.owner),None)
                if not target or not eligible(target,p,data):raise HTTPException(400,'新所有者须为启用用户，并具有项目智能体权限')
                p['owner']=body.owner
                save(data)
        return {'ok':True,'owner':body.owner}
