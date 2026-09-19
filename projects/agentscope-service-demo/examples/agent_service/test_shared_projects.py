"""Live shared directory/private chat regressions; unique temporary records only."""
import asyncio
import hashlib
import json
import shutil
from uuid import uuid4
from types import SimpleNamespace
import requests
import portal
from project_files import ROOT, ProjectFiles, membership
from skill_packages import workdir

BASE = 'http://127.0.0.1:5173/api/service'
tag = uuid4().hex[:8]
owner, member, outsider = ['shared-' + tag + '-' + x for x in ('owner', 'member', 'outsider')]
agent = other_agent = pid = None
sessions = []
checks = 0

def call(user, method, path, body=None, status=200, files=None):
    global checks
    r = requests.request(method, BASE + path, headers={'X-User-ID': user}, json=body, files=files, timeout=25)
    assert r.status_code == status, (path, r.status_code, r.text[:300])
    checks += 1
    return r.json() if r.content and 'json' in r.headers.get('content-type', '') else r.content

def grant(user, aid):
    call('wei', 'PUT', '/portal/grants', {'subject_type':'user','subject':user,'agent_id':aid})

try:
    for u in (owner, member, outsider): call('wei','PUT','/portal/users',{'username':u})
    agent = call('wei','POST','/agent/',{'name':'shared-test-'+tag},201)['agent_id']
    other_agent = call('wei','POST','/agent/',{'name':'shared-other-'+tag},201)['agent_id']
    for u in (owner,member): grant(u,agent)
    grant(member, other_agent)
    p = call(owner,'POST','/portal/projects',{'name':'private-by-default','agent_id':agent})
    pid = p['id']; assert p['shared'] is False
    assert not any(p['id']==pid for p in call(member,'GET','/portal/projects')['projects'])
    call(member,'GET',f'/portal/projects/{pid}/files',status=404)
    call(owner,'PUT',f'/portal/projects/{pid}',{'name':'shared-directory','shared':True})
    rows = [p for p in call(member,'GET','/portal/projects')['projects'] if p['id']==pid]
    assert len(rows)==1 and rows[0]['id']==pid and not rows[0]['is_owner']
    assert not any(p['id']==pid for p in call(outsider,'GET','/portal/projects')['projects'])
    call(outsider,'GET',f'/portal/projects/{pid}/files',status=404)
    call(member,'PUT',f'/portal/projects/{pid}',{'name':'forbidden','shared':False},404)
    for u in (owner, member):
        sid=call(u,'POST','/sessions/',{'agent_id':agent,'name':u+'-PRIVATE'},201)['session_id']
        sessions.append((u,agent,sid))
        call(u,'POST',f'/portal/projects/{pid}/sessions',{'agent_id':agent,'session_id':sid})
    a,b=[s[2] for s in sessions]
    capability = call(owner,'GET',f'/portal/capabilities/{agent}/{a}')
    assert capability['has_selection'] is False
    defaults = {k:[r['id'] for r in capability['catalog'][k]] for k in ('mcps','skills','knowledge')}
    call(owner,'PUT',f'/portal/capabilities/{agent}/{a}',defaults)
    applied = call(owner,'GET',f'/portal/capabilities/{agent}/{a}')
    assert applied['has_selection'] is True and applied['selected']==defaults
    call(owner,'PUT',f'/portal/capabilities/{agent}/{a}',{'mcps':[],'skills':[],'knowledge':[]})
    cleared = call(owner,'GET',f'/portal/capabilities/{agent}/{a}')
    assert cleared['has_selection'] is True and not any(cleared['selected'].values())
    call(owner,'POST','/portal/session-pins',{'agent_id':agent,'session_id':a,'pinned':True})
    assert {'agent_id':agent,'session_id':a} in call(owner,'GET','/portal/session-pins')
    assert not call(member,'GET','/portal/session-pins')
    call(member,'POST','/portal/session-pins',{'agent_id':agent,'session_id':a,'pinned':True},404)
    call(owner,'POST','/portal/session-pins',{'agent_id':agent,'session_id':a,'pinned':False})
    assert not call(owner,'GET','/portal/session-pins')
    call(owner,'PATCH',f'/sessions/{a}?agent_id={agent}',{'name':'renamed private session'})
    assert call(owner,'GET',f'/portal/projects/{pid}/sessions')[0]['name']=='renamed private session'
    own_rows=call(owner,'GET',f'/portal/projects/{pid}/sessions')
    member_rows=call(member,'GET',f'/portal/projects/{pid}/sessions')
    assert [r['session_id'] for r in own_rows]==[a]
    assert [r['session_id'] for r in member_rows]==[b]
    assert all(r['session_id']!=a for r in call(member,'GET','/portal/projects')['bindings'])
    call(member,'GET',f'/portal/session-project/{agent}/{a}',status=404)
    call(member,'POST',f'/portal/projects/{pid}/sessions',{'agent_id':agent,'session_id':a},404)
    wrong=call(member,'POST','/sessions/',{'agent_id':other_agent},201)['session_id'];sessions.append((member,other_agent,wrong))
    call(member,'POST',f'/portal/projects/{pid}/sessions',{'agent_id':other_agent,'session_id':wrong},403)
    call(owner,'POST',f'/portal/projects/{pid}/files',files={'file':('source.txt',b'OWNER_INPUT')})
    assert call(member,'GET',f'/portal/skill-files/{agent}/{b}/source.txt')==b'OWNER_INPUT'
    assert workdir(owner,agent,a)==workdir(member,agent,b)
    async def write():
        tool=ProjectFiles(SimpleNamespace(username=member,agent=agent,session=b))
        result=await tool.call('write',name='member.txt',content='MEMBER_OUTPUT')
        assert result.state.value=='success',str(result)
    asyncio.run(write())
    assert call(owner,'GET',f'/portal/projects/{pid}/files/member.txt')==b'MEMBER_OUTPUT'
    call(member,'POST',f'/portal/projects/{pid}/file-actions/rename',{'name':'member.txt','new_name':'renamed.txt'})
    call(owner,'PUT',f'/portal/projects/{pid}',{'name':'shared-directory','agent_id':other_agent},409)
    versions = call(owner,'GET',f'/portal/projects/{pid}/history')
    entry = versions[0]
    deletion = {'name':entry['name'],'version':entry['version'],'confirmed':True}
    call(owner,'POST',f'/portal/projects/{pid}/history/delete',{**deletion,'confirmed':False},400)
    call(member,'POST',f'/portal/projects/{pid}/history/delete',deletion,404)
    call(owner,'POST',f'/portal/projects/{pid}/history/delete',{**deletion,'version':'../'},400)
    call(owner,'POST',f'/portal/projects/{pid}/history/delete',deletion)
    remaining = call(owner,'GET',f'/portal/projects/{pid}/history')
    assert len(remaining)==len(versions)-1
    assert not any(v['name']==entry['name'] and v['version']==entry['version'] for v in remaining)
    assert call(owner,'GET',f'/portal/projects/{pid}/files/renamed.txt')==b'MEMBER_OUTPUT'
    assert call(owner,'GET',f'/portal/projects/{pid}/files/source.txt')==b'OWNER_INPUT'
    call(owner,'PUT',f'/portal/projects/{pid}',{'name':'private-again','shared':False})
    assert not any(p['id']==pid for p in call(member,'GET','/portal/projects')['projects'])
    call(member,'GET',f'/portal/skill-files/{agent}/{b}/source.txt',status=404)
    async def denied():
        result=await ProjectFiles(SimpleNamespace(username=member,agent=agent,session=b)).call('list')
        assert result.state.value=='error'
    asyncio.run(denied())
    call(owner,'PUT',f'/portal/projects/{pid}',{'name':'shared-again','shared':True})
    # Revoke only the fixture user's agent grant, retaining the user and other-agent grant.
    with portal.LOCK:
        data=portal.load()
        data['grants']=[g for g in data['grants'] if not(g['subject_type']=='user' and g['subject']==member and g['agent_id']==agent)]
        portal.save(data)
    assert not any(p['id']==pid for p in call(member,'GET','/portal/projects')['projects'])
    call(member,'GET',f'/portal/projects/{pid}/files',status=404)
    asyncio.run(denied())
    grant(member,agent)
    assert call(member,'GET',f'/portal/projects/{pid}/files/renamed.txt')==b'MEMBER_OUTPUT'
    call(member,'POST',f'/portal/projects/{pid}/delete',{'confirmed':True},404)
    call(owner,'POST',f'/portal/projects/{pid}/delete',{'confirmed':False},400)
    assert any(p['id']==pid for p in call(owner,'GET','/portal/projects')['projects'])
    call(owner,'POST',f'/portal/projects/{pid}/delete',{'confirmed':True})
    assert all(p['id']!=pid for p in call(owner,'GET','/portal/projects')['projects'])
    assert all(p['id']!=pid for p in call(member,'GET','/portal/projects')['projects'])
    call(owner,'GET',f'/portal/projects/{pid}/files',status=404)
    call(member,'GET',f'/portal/skill-files/{agent}/{b}/source.txt',status=404)
    assert (ROOT/pid/'files'/'source.txt').read_bytes()==b'OWNER_INPUT'
    print(f'PASS {checks} checks: private default, shared discovery and writes, private sessions, wrong-agent denial, sharing/grant revocation, restore access.')
finally:
    for u,aid,sid in sessions: call(u,'DELETE',f'/sessions/{sid}?agent_id={aid}',status=204)
    for aid in (agent,other_agent):
        if aid: call('wei','DELETE','/agent/'+aid,status=204)
    for u in (owner,member,outsider): call('wei','DELETE','/portal/users/'+u)
    if pid:
        with portal.LOCK:
            data=portal.load();data.get('projects',{}).pop(pid,None)
            data['project_sessions']={k:v for k,v in data.get('project_sessions',{}).items() if v!=pid}
            portal.save(data)
        folder=ROOT/pid
        history=ROOT/'history'/hashlib.sha256(str((folder/'files').resolve()).encode()).hexdigest()
        for path in (folder,history):
            if path.exists(): shutil.rmtree(path)
