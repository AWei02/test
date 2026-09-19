"""Project-bound channels use scoped files and an explicit capability snapshot."""
from fastapi import HTTPException

FIELDS = ('mcps', 'skills', 'knowledge')

async def validate(storage, username, settings, bindings):
    from portal import ADMIN, catalog
    from project_files import accessible
    pid = settings.get('project_id')
    if not pid:
        return
    if username != ADMIN:
        raise HTTPException(403, '频道仅由管理员配置')
    project = accessible(username, pid)
    if not project.get('agent_id') or any(b['agent_id'] != project['agent_id'] for b in bindings):
        raise HTTPException(400, '频道路由必须使用所绑定项目的智能体')
    selected = settings.get('capabilities')
    if selected is not None:
        resources = await catalog(storage)
        if set(selected) != set(FIELDS) or any(not isinstance(selected[k], list) or not set(selected[k]) <= {r['id'] for r in resources[k]} for k in FIELDS):
            raise HTTPException(400, '能力包含不存在或已停用的资源，请重新选择')

async def prepare(storage, record, agent, sid):
    from portal import load, save, LOCK, catalog
    from project_files import accessible, member_key
    settings = record.session
    if not settings.project_id:
        return None
    project = accessible(record.user_id, settings.project_id)
    if project.get('agent_id') != agent:
        raise HTTPException(403, '频道智能体与项目不一致')
    resources = await catalog(storage)
    selected = settings.capabilities
    # Null is a legacy/default value. The UI persists an explicit initial snapshot.
    selected = {k: [r['id'] for r in resources[k] if selected is None or r['id'] in selected.get(k, [])] for k in FIELDS}
    with LOCK:
        data = load()
        key = member_key(record.user_id, agent, sid)
        previous = data.setdefault('project_sessions', {}).get(key)
        if previous and previous != project['id']:
            raise HTTPException(409, '已有频道会话不可切换项目，请新建频道')
        data['project_sessions'][key] = project['id']
        save(data)
    return selected
