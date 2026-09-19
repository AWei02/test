"""Live role lifecycle checks using dedicated temporary records, no model calls."""
from uuid import uuid4
import requests
from portal import ADMIN

base = 'http://127.0.0.1:5173/api/service'
role = 'role-test-' + uuid4().hex[:10]
username = 'user-' + role
checks = 0
grant_id = None
def call(method, path, body=None, status=200, user=ADMIN):
    global checks
    r = requests.request(method, base + path, headers={'X-User-ID':user}, json=body, timeout=25)
    assert r.status_code == status, (path, r.status_code, r.text[:250])
    checks += 1
    return r.json()
try:
    call('POST','/portal/roles',{'name':'  '},400)
    call('POST','/portal/roles',{'name':' '+role+' '})
    call('POST','/portal/roles',{'name':role},409)
    call('PUT','/portal/users',{'username':username,'role':role+'missing'},400)
    call('PUT','/portal/users',{'username':username,'role':role,'enabled':False})
    call('POST','/portal/roles/delete',{'name':role},400)
    assert username in call('POST','/portal/roles/delete',{'name':role,'confirmed':True},409)['detail']
    call('PUT','/portal/users',{'username':username,'role':role,'enabled':True})
    call('POST','/portal/roles',{'name':role+'other'},403,user=username)
    call('POST','/portal/roles/delete',{'name':role,'confirmed':True},403,user=username)
    state = call('GET','/portal/admin')
    agent = state['catalog']['agents'][0]['id']
    call('PUT','/portal/grants',{'subject_type':'role','subject':role,'agent_id':agent})
    state = call('GET','/portal/admin')
    grant_id = next(g['id'] for g in state['grants'] if g['subject_type']=='role' and g['subject']==role)
    call('DELETE','/portal/users/'+username)
    assert grant_id in call('POST','/portal/roles/delete',{'name':role,'confirmed':True},409)['detail']
    call('DELETE','/portal/grants/'+grant_id)
    call('POST','/portal/roles/delete',{'name':role,'confirmed':True})
    assert role not in call('GET','/portal/admin')['roles']
    call('PUT','/portal/grants',{'subject_type':'role','subject':role,'agent_id':agent},400)
    call('PUT','/portal/users',{'username':username,'role':role},400)
    print(f'PASS {checks} role lifecycle, reference protection, dropdown source and authorization checks')
finally:
    call('DELETE','/portal/users/'+username)
    if grant_id: call('DELETE','/portal/grants/'+grant_id)
    state = call('GET','/portal/admin')
    if role in state['roles']: call('POST','/portal/roles/delete',{'name':role,'confirmed':True})
