"""Live project/file regression checks. Creates and removes only unique fixtures."""
import asyncio
import json
from pathlib import Path
import shutil
import tempfile
import subprocess
from unittest.mock import AsyncMock, patch
import skill_packages as packages
from types import SimpleNamespace
from uuid import uuid4
import requests
import portal
from project_files import ROOT, ProjectFiles, project_directory, membership
from skill_packages import workdir

BASE='http://127.0.0.1:5173/api/service'
suffix=uuid4().hex[:8]
alice,bob='proj-a-'+suffix,'proj-b-'+suffix
agent=None
projects=[]
sessions=[]
checks=0
def call(user,method,path,body=None,status=200,files=None):
    global checks
    r=requests.request(method,BASE+path,headers={'X-User-ID':user},json=body,files=files,timeout=30)
    assert r.status_code==status,(path,r.status_code,r.text[:300])
    checks+=1
    return r.json() if r.content and 'json' in r.headers.get('content-type','') else r.content

try:
    for user in (alice,bob):call('wei','PUT','/portal/users',{'username':user})
    agent=call('wei','POST','/agent/',{'name':'project-test-'+suffix},201)['agent_id']
    for user in (alice,bob):call('wei','PUT','/portal/grants',{'subject_type':'user','subject':user,'agent_id':agent})
    p=call(alice,'POST','/portal/projects',{'name':'共享文件测试','description':'test'})['id'];projects.append(p)
    p2=call(alice,'POST','/portal/projects',{'name':'独立项目'})['id'];projects.append(p2)
    call(bob,'GET',f'/portal/projects/{p}/files',status=404)
    for i in range(3):
        sid=call(alice,'POST','/sessions/',{'agent_id':agent},201)['session_id'];sessions.append(sid)
        if i<2:call(alice,'POST',f'/portal/projects/{p}/sessions',{'agent_id':agent,'session_id':sid})
    call(alice,'POST',f'/portal/projects/{p2}/sessions',{'agent_id':agent,'session_id':sessions[0]},409)
    call(alice,'POST',f'/portal/projects/{p}/files',files={'file':('input.txt',b'PROJECT_INPUT')})
    call(alice,'POST',f'/portal/projects/{p}/files',files={'file':('input.txt',b'overwrite')},status=409)
    for sid in sessions[:2]:
        assert call(alice,'GET',f'/portal/skill-files/{agent}/{sid}/input.txt')==b'PROJECT_INPUT'
    call(alice,'GET',f'/portal/skill-files/{agent}/{sessions[2]}/input.txt',status=404)
    call(bob,'GET',f'/portal/skill-files/{agent}/{sessions[0]}/input.txt',status=404)
    assert workdir(alice,agent,sessions[0])==workdir(alice,agent,sessions[1])
    assert workdir(alice,agent,sessions[2])!=workdir(alice,agent,sessions[0])
    file_url=f'/portal/skill-files/{agent}/{sessions[2]}'
    call(alice,'POST',file_url,files={'file':('delete-test.txt',b'DELETE_FIXTURE')})
    call(bob,'DELETE',file_url+'/delete-test.txt?confirmed=true',status=404)
    call(alice,'DELETE',file_url+'/delete-test.txt',status=400)
    assert call(alice,'GET',file_url+'/delete-test.txt')==b'DELETE_FIXTURE'
    result=call(alice,'DELETE',file_url+'/delete-test.txt?confirmed=true')
    assert result['backup_version']
    call(alice,'GET',file_url+'/delete-test.txt',status=404)
    call(alice,'DELETE',f'/portal/skill-files/{agent}/{sessions[0]}/input.txt?confirmed=true',status=409)
    async def tools():
        ws=SimpleNamespace(username=alice,agent=agent,session=sessions[0])
        result=await ProjectFiles(ws).call('write',name='report.txt',content='AI_RESULT')
        assert result.state.value=='success',str(result)
        ws2=SimpleNamespace(username=alice,agent=agent,session=sessions[1])
        result=await ProjectFiles(ws2).call('read',name='report.txt')
        assert result.content[0].text=='AI_RESULT'
    asyncio.run(tools())
    async def shared_script():
        tag = 'portal-project-test:' + suffix
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / 's1' / 'content'
                root.mkdir(parents=True)
                (root / 'SKILL.md').write_text('---\nname: project-test\ndescription: test\n---\nRun demo.py')
                (root / 'demo.py').write_text('from pathlib import Path\nPath("script.txt").write_text(Path("input.txt").read_text()+"_SCRIPT")\n')
                packages.build_image(root, tag)
                (root.parent / 'manifest.json').write_text(json.dumps({'image':tag}))
                record = SimpleNamespace(id='s1',name='project-test',description='test',markdown='test',enabled=True)
                ws = SimpleNamespace(username=alice,agent=agent,session=sessions[0],
                    selected=lambda field: {'s1'},storage=SimpleNamespace(get_skill=AsyncMock(return_value=record)))
                with patch.object(packages,'ROOT',Path(temp)):
                    result = await packages.RunSkill(ws).call('s1','demo.py','run')
                    assert result.state.value=='success',str(result)
                assert call(alice,'GET',f'/portal/skill-files/{agent}/{sessions[1]}/script.txt')==b'PROJECT_INPUT_SCRIPT'
        finally:
            subprocess.run(['docker','image','rm',tag],capture_output=True)
    asyncio.run(shared_script())
    call(alice,'POST',f'/portal/projects/{p}/file-actions/rename',{'name':'report.txt','new_name':'final.txt'})
    call(alice,'POST',f'/portal/projects/{p}/file-actions/delete',{'name':'final.txt'})
    hist=call(alice,'GET',f'/portal/projects/{p}/history')
    item=next(h for h in hist if h['name']=='final.txt')
    call(alice,'POST',f'/portal/projects/{p}/file-actions/restore',item)
    assert call(alice,'GET',f'/portal/projects/{p}/files/final.txt')==b'AI_RESULT'
    call(alice,'POST',f'/portal/projects/{p}/file-actions/delete',{'name':'../escape'},400)
    rows=call(alice,'GET',f'/portal/projects/{p}/sessions');assert len(rows)==2
    print(f'PASS {checks} project API checks; two sessions share files, ordinary sessions/private projects isolated; AI file tool; rename/delete/restore.')
finally:
    for sid in sessions:call(alice,'DELETE',f'/sessions/{sid}?agent_id={agent}',status=204)
    if agent:call('wei','DELETE','/agent/'+agent,status=204)
    for user in (alice,bob):call('wei','DELETE','/portal/users/'+user)
    with portal.LOCK:
        data=portal.load()
        for pid in projects:data.get('projects',{}).pop(pid,None)
        data['project_sessions']={k:v for k,v in data.get('project_sessions',{}).items() if v not in projects}
        portal.save(data)
    for pid in projects:
        path=ROOT/pid
        if path.exists():shutil.rmtree(path)
