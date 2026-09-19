"""Live fixture-only project ownership and agent deletion regressions."""
import requests
from uuid import uuid4
import portal
from project_files import ROOT
import shutil
import hashlib
base='http://127.0.0.1:5173/api/service';tag=uuid4().hex[:10]
role='transfer-'+tag;owner='owner-'+tag;target='target-'+tag;other='other-'+tag
aid=pid=sid=None;checks=0
def call(user,method,path,body=None,status=200,files=None):
    global checks
    r=requests.request(method,base+path,headers={'X-User-ID':user},json=body,files=files,timeout=25)
    assert r.status_code==status,(path,r.status_code,r.text[:200])
    checks+=1
    return r.json() if r.content and 'json' in r.headers.get('content-type','') else r.content
try:
    call(portal.ADMIN,'POST','/portal/roles',{'name':role})
    for u in (owner,target,other):call(portal.ADMIN,'PUT','/portal/users',{'username':u,'role':role})
    aid=call(portal.ADMIN,'POST','/agent/',{'name':'transfer-fixture-'+tag},201)['agent_id']
    for u in (owner,target):call(portal.ADMIN,'PUT','/portal/grants',{'subject_type':'user','subject':u,'agent_id':aid})
    pid=call(owner,'POST','/portal/projects',{'name':'transfer-fixture','agent_id':aid})['id']
    sid=call(owner,'POST','/sessions/',{'agent_id':aid},201)['session_id']
    call(owner,'POST',f'/portal/projects/{pid}/sessions',{'agent_id':aid,'session_id':sid})
    call(owner,'POST',f'/portal/projects/{pid}/files',files={'file':('fixture.txt',b'PRESERVED')})
    options=call(owner,'GET',f'/portal/projects/{pid}/transfer-options')
    assert portal.ADMIN in options['users'] and target in options['users'] and other not in options['users']
    call(other,'GET',f'/portal/projects/{pid}/transfer-options',status=403)
    body={'owner':target,'expected_owner':owner,'confirmed':True}
    call(owner,'POST',f'/portal/projects/{pid}/transfer',{**body,'confirmed':False},400)
    call(owner,'POST',f'/portal/projects/{pid}/transfer',{**body,'owner':other},400)
    call(owner,'POST',f'/portal/projects/{pid}/transfer',body)
    assert call(target,'GET',f'/portal/projects/{pid}/files/fixture.txt')==b'PRESERVED'
    assert not call(target,'GET',f'/portal/projects/{pid}/sessions')
    call(owner,'GET',f'/portal/projects/{pid}/files',status=404)
    call(owner,'POST',f'/portal/projects/{pid}/transfer',body,403)
    call(portal.ADMIN,'POST',f'/portal/projects/{pid}/transfer',{'owner':portal.ADMIN,'expected_owner':owner,'confirmed':True},409)
    call(portal.ADMIN,'POST',f'/portal/projects/{pid}/transfer',{'owner':portal.ADMIN,'expected_owner':target,'confirmed':True})
    assert portal.load()['project_sessions'][__import__('json').dumps([owner,aid,sid])]==pid
    blocked=call(portal.ADMIN,'DELETE','/agent/'+aid,status=409)
    assert '授权编码' in blocked['detail']
    call(portal.ADMIN,'PUT','/portal/grants',{'subject_type':'role','subject':role,'agent_id':aid})
    grants=call(portal.ADMIN,'GET','/portal/admin')['grants']
    for g in grants:
        if g['agent_id']==aid and g['subject_type']=='user':call(portal.ADMIN,'DELETE','/portal/grants/'+g['id'])
    call(portal.ADMIN,'DELETE','/agent/'+aid,status=409)
    for g in grants:
        if g['agent_id']==aid and g['subject_type']=='role':call(portal.ADMIN,'DELETE','/portal/grants/'+g['id'])
    call(portal.ADMIN,'DELETE','/agent/'+aid,status=204);aid=None
    print(f'PASS {checks} project transfer, unchanged files/private sessions, permission checks and user/role grant deletion guards')
finally:
    for u in (owner,target,other):call(portal.ADMIN,'DELETE','/portal/users/'+u)
    data=portal.load()
    for g in list(data['grants']):
        if aid and g['agent_id']==aid:call(portal.ADMIN,'DELETE','/portal/grants/'+g['id'])
    if aid:call(portal.ADMIN,'DELETE','/agent/'+aid,status=204)
    call(portal.ADMIN,'POST','/portal/roles/delete',{'name':role,'confirmed':True})
    if pid:
        with portal.LOCK:
            data=portal.load();data.get('projects',{}).pop(pid,None);portal.save(data)
        folder=ROOT/pid
        hist=ROOT/'history'/hashlib.sha256(str((folder/'files').resolve()).encode()).hexdigest()
        for p in (folder,hist):
            if p.exists():shutil.rmtree(p)
