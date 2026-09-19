"""Run against the learning server: python portal_smoke.py.

Creates uniquely named test users/resources; removes exactly those records.
No external model call, API key, or paid service is used.
"""
import json
import os
import urllib.request
import urllib.error
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4
from agentscope.message import UserMsg

BASE = os.getenv('PORTAL_TEST_URL', 'http://127.0.0.1:5173/api/service')
ADMIN = os.getenv('PORTAL_ADMIN', 'wei')
suffix = uuid4().hex[:8]
alice, bob = 'test-a-' + suffix, 'test-b-' + suffix
agent = None
credential = None
knowledge = None
sessions = []
checks = 0
model_requests = []
skill_id = None
skill_test = os.getenv('PORTAL_SKILL_TEST') == '1'

class MockModel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        model_requests.append(body)
        self.send_response(200)
        if self.path.endswith('/embeddings'):
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            inputs = body.get('input', ['query'])
            count = len(inputs) if isinstance(inputs, list) else 1
            self.wfile.write(json.dumps({'object': 'list', 'model': body.get('model'),
                'data': [{'object': 'embedding', 'index': i, 'embedding': [1.0] + [0.0] * 1535}
                         for i in range(count)], 'usage': {'prompt_tokens': 1, 'total_tokens': 1}}).encode())
            return
        if body.get('stream'):
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            deltas = [({'role': 'assistant', 'content': 'PORTAL_OK'}, None), ({}, 'stop')]
            if skill_test and not any(m.get('role') == 'tool' for m in body.get('messages', [])):
                deltas = [({'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'skill-call', 'type': 'function',
                    'function': {'name': 'RunSkill', 'arguments': json.dumps({'skill_id': skill_id,
                        'path': 'demo.py', 'action': 'run', 'args': []})}}]}, None), ({}, 'tool_calls')]
            for delta, reason in deltas:
                chunk = {'id': 'mock-completion', 'object': 'chat.completion.chunk', 'created': 1,
                    'model': 'portal-test', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': reason}]}
                self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        else:
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'id': 'mock-completion', 'object': 'chat.completion',
                'created': 1, 'model': 'portal-test', 'choices': [{'index': 0,
                'message': {'role': 'assistant', 'content': '{"title":"Portal test"}'},
                'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 1, 'completion_tokens': 1,
                'total_tokens': 2}}).encode())

model_server = ThreadingHTTPServer(('127.0.0.1', 0), MockModel)
threading.Thread(target=model_server.serve_forever, daemon=True).start()

def request(user, method, path, body=None, status=200):
    global checks
    req = urllib.request.Request(BASE + path, method=method,
        headers={'X-User-ID': user, 'Content-Type': 'application/json'},
        data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            code, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        code, raw = error.code, error.read()
    assert code == status, (method, path, code, raw.decode()[:500])
    checks += 1
    return json.loads(raw) if raw else None

try:
    request(ADMIN, 'GET', '/portal/me')
    request('unknown-' + suffix, 'GET', '/portal/me', status=403)
    for username in (alice, bob):
        request(ADMIN, 'PUT', '/portal/users', {'username': username, 'role': '普通用户'})
    request(alice, 'GET', '/portal/admin', status=403)
    if skill_test:
        from test_skill_packages import archive
        raw = archive({'SKILL.md': f'---\nname: smoke-{suffix}\ndescription: Run demo.py\n---\nUse RunSkill to run demo.py',
            'demo.py': 'from pathlib import Path\nPath("result.txt").write_text("LIVE_SKILL_OK")\nprint("LIVE_SKILL_OK")'})
        boundary = 'portal-test-' + suffix
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="skill.zip"\r\nContent-Type: application/zip\r\n\r\n'.encode()
                + raw + f'\r\n--{boundary}--\r\n'.encode())
        req = urllib.request.Request(BASE + '/portal/skill-packages', method='POST', data=body,
            headers={'X-User-ID': ADMIN, 'Content-Type': 'multipart/form-data; boundary=' + boundary})
        with urllib.request.urlopen(req, timeout=320) as response:
            skill_id = json.load(response)['id']
    request(alice, 'POST', '/agent/', {'name': 'forbidden'}, status=403)
    agent = request(ADMIN, 'POST', '/agent/', {'name': 'portal-test-' + suffix}, 201)['agent_id']
    request(bob, 'POST', '/sessions/', {'agent_id': agent}, status=403)
    grant = {'subject_type': 'user', 'subject': alice, 'agent_id': agent}
    request(ADMIN, 'PUT', '/portal/grants', grant)
    visible = request(alice, 'GET', '/agent/')
    assert any(a['id'] == agent and not a['editable'] for a in visible['agents'])
    assert not any(a['id'] == agent for a in request(bob, 'GET', '/agent/')['agents'])
    sid = request(alice, 'POST', '/sessions/', {'agent_id': agent, 'name': 'Portal test'}, 201)['session_id']
    sessions.append((alice, sid))
    request(alice, 'GET', f'/portal/capabilities/{agent}/{sid}')
    request(alice, 'PUT', f'/portal/capabilities/{agent}/{sid}', {})
    request(alice, 'PUT', f'/portal/capabilities/{agent}/{sid}', {'knowledge': ['forbidden']}, 403)
    request(alice, 'PUT', f'/portal/capabilities/{agent}/{sid}', {'mcps': ['forbidden']}, 403)
    request(alice, 'PUT', f'/portal/capabilities/{agent}/{sid}', {'skills': ['forbidden']}, 403)
    request(alice, 'PATCH', f'/sessions/{sid}?agent_id={agent}', {'permission_mode': 'bypass'}, 403)
    request(alice, 'POST', '/sessions/', {'agent_id': agent, 'workspace_id': 'other-user'}, 403)
    request(alice, 'POST', '/workspace/mcp', {}, 403)
    request(ADMIN, 'PUT', '/portal/grants', {**grant, 'subject': bob})
    request(bob, 'GET', f'/sessions/{sid}/messages?agent_id={agent}', status=404)
    request(bob, 'PUT', f'/portal/capabilities/{agent}/{sid}', {}, 404)
    credential = request(ADMIN, 'POST', '/credential/', {'data': {
        'type': 'openai_credential', 'api_key': 'local-test-only',
        'base_url': f'http://127.0.0.1:{model_server.server_port}/v1'}}, 201)['credential_id']
    knowledge = request(ADMIN, 'POST', '/knowledge_bases/', {
        'name': 'portal-test-kb-' + suffix,
        'embedding_model_config': {'type': 'openai_credential', 'credential_id': credential,
            'model': 'text-embedding-3-small', 'dimensions': 1536}}, 201)['knowledge_base_id']
    request(ADMIN, 'PUT', '/portal/grants', {**grant, 'credentials': [credential], 'knowledge': [knowledge], 'skills': [skill_id] if skill_id else []})
    request(alice, 'PUT', f'/portal/capabilities/{agent}/{sid}', {'knowledge': [knowledge], 'skills': [skill_id] if skill_id else []})
    request(alice, 'PATCH', f'/sessions/{sid}?agent_id={agent}', {'chat_model_config': {
        'type': 'openai_credential', 'credential_id': credential, 'model': 'portal-test', 'parameters': {}}})
    request(alice, 'POST', '/chat/', {'agent_id': agent, 'session_id': sid,
        'input': UserMsg(name='user', content='Reply with PORTAL_OK').model_dump(mode='json')})
    for _ in range(60):
        result = request(alice, 'GET', f'/sessions/{sid}/messages?agent_id={agent}')
        if any(m.get('role') == 'assistant' and 'PORTAL_OK' in json.dumps(m) for m in result['messages']) and not result['is_running']:
            break
        time.sleep(0.2)
    else:
        raise AssertionError('Chat did not complete; model requests=' + str(len(model_requests)) + ': ' + json.dumps(result))
    tool_names = {t['function']['name'] for r in model_requests for t in r.get('tools', [])}
    assert 'search_knowledge' in tool_names, tool_names
    assert not {'Bash', 'AgentCreate', 'TeamCreate'} & tool_names, tool_names
    if skill_test:
        assert 'RunSkill' in tool_names, tool_names
        assert any('LIVE_SKILL_OK' in json.dumps(r.get('messages')) for r in model_requests)
        files = request(alice, 'GET', f'/portal/skill-files/{agent}/{sid}')
        assert 'result.txt' in files['files'], files
        req = urllib.request.Request(BASE + f'/portal/skill-files/{agent}/{sid}/result.txt', headers={'X-User-ID': alice})
        with urllib.request.urlopen(req) as response:
            assert response.read() == b'LIVE_SKILL_OK'
        request(bob, 'GET', f'/portal/skill-files/{agent}/{sid}', status=404)
    request(ADMIN, 'PUT', '/portal/grants', {**grant, 'credentials': [credential]})
    request(alice, 'POST', '/chat/', {'agent_id': agent, 'session_id': sid, 'input': None}, 403)
    request(ADMIN, 'PUT', '/portal/grants', {**grant, 'credentials': [credential], 'knowledge': [knowledge]})
    request(ADMIN, 'PUT', '/portal/users', {'username': bob, 'enabled': False})
    request(bob, 'GET', '/agent/', status=403)
    print(f'PASS: {checks} live API checks; real Agent reply_stream completed with local mock model; RAG tool attached; host/team tools absent.')
    if skill_test:
        print('PASS: ZIP upload -> grant -> selected skill -> Agent RunSkill -> Docker script -> downloadable output; cross-user access denied.')
finally:
    for username, sid in sessions:
        request(username, 'DELETE', f'/sessions/{sid}?agent_id={agent}', status=204)
    if agent:
        request(ADMIN, 'DELETE', '/agent/' + agent, status=204)
    if knowledge:
        request(ADMIN, 'DELETE', '/knowledge_bases/' + knowledge, status=204)
    if credential:
        request(ADMIN, 'DELETE', '/credential/' + credential, status=204)
    if skill_id:
        import subprocess
        import shutil
        from skill_packages import ROOT, workdir
        request(ADMIN, 'DELETE', '/skill/' + skill_id, status=204)
        subprocess.run(['docker', 'image', 'rm', 'portal-skill:' + skill_id], capture_output=True)
        shutil.rmtree(ROOT / skill_id)
        for username, sid in sessions:
            shutil.rmtree(workdir(username, agent, sid))
    for username in (alice, bob):
        request(ADMIN, 'DELETE', '/portal/users/' + username)
    model_server.shutdown()
    model_server.server_close()
