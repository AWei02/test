"""Disabled fixture channel only; never connects to Feishu or calls a model."""
from uuid import uuid4
import requests
import portal
base='http://127.0.0.1:5173/api/service'
tag=uuid4().hex
pid=cid=None
checks=0
def call(method,path,body=None,status=200):
    global checks
    r=requests.request(method,base+path,headers={'X-User-ID':portal.ADMIN},json=body,timeout=25)
    assert r.status_code==status,(path,r.status_code,r.text[:250])
    checks+=1
    return r.json() if r.content else None
try:
    state=call('GET','/portal/admin')
    aid=state['catalog']['agents'][0]['id']
    pid=call('POST','/portal/projects',{'name':'channel-fixture-'+tag,'agent_id':aid})['id']
    selected={k:[x['id'] for x in state['catalog'][k]] for k in ('mcps','skills','knowledge')}
    settings={'project_id':pid,'capabilities':selected,'chat_model_config':{'type':'openai','model':'fixture','credential_id':'fixture'},'permission_mode':'default'}
    payload={'name':'disabled-fixture-'+tag,'channel_type':'feishu','enabled':False,'credentials':{'app_id':'cli_fixture_'+tag,'app_secret':'test-only'},'routing':{'bindings':[{'match_value':'*','agent_id':aid,'session_scope':'per_chat_user'}]},'session':settings}
    record=call('POST','/channels/',payload,201);cid=record['id']
    assert record['session']['project_id']==pid and record['session']['capabilities']==selected
    assert record['enabled'] is False
    call('PATCH','/channels/'+cid,{'session':{**settings,'project_id':None}},409)
    call('PATCH','/channels/'+cid,{'session':{**settings,'capabilities':{'mcps':['not-real'],'skills':[],'knowledge':[]}}},400)
    empty={k:[] for k in selected}
    call('PATCH','/channels/'+cid,{'session':{**settings,'capabilities':empty}})
    updated=call('GET','/channels/'+cid)
    assert updated['session']['capabilities']==empty and not updated['enabled']
    print(f'PASS {checks} live channel project persistence, edit and invalid configuration checks')
finally:
    if cid:call('DELETE','/channels/'+cid,status=204)
    if pid:
        with portal.LOCK:
            data=portal.load();data.get('projects',{}).pop(pid,None);portal.save(data)
