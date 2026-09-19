"""Verify first-session model persistence without sending any model requests."""
import json
from urllib.request import Request, urlopen
from urllib.parse import urlencode


def request(method, path, body=None):
    req = Request('http://127.0.0.1:8000' + path,
                  data=json.dumps(body).encode() if body is not None else None,
                  method=method, headers={'X-User-ID': 'wei', 'Content-Type': 'application/json'})
    with urlopen(req, timeout=15) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


if __name__ == '__main__':
    agents = request('GET', '/agent/')['agents']
    credentials = request('GET', '/credential/')['credentials']
    credential = next(c for c in credentials if c['data']['type'] == 'deepseek_credential')
    models = request('GET', '/portal/models/' + credential['id'])['models']
    assert agents and models
    agent_id = agents[0]['id']
    config = {'type': credential['data']['type'], 'credential_id': credential['id'],
              'model': models[0]['name'], 'parameters': {}}
    session_id = None
    try:
        session_id = request('POST', '/sessions/', {'agent_id': agent_id, 'chat_model_config': config})['session_id']
        query = '?' + urlencode({'agent_id': agent_id})
        def saved():
            rows = request('GET', '/sessions/' + query)['sessions']
            return next(row['session']['config']['chat_model_config'] for row in rows
                        if row['session']['id'] == session_id)
        assert saved() == config
        print('PASS: first session stores and reloads selected model')
        if len(models) > 1:
            config['model'] = models[1]['name']
            request('PATCH', '/sessions/' + session_id + query, {'chat_model_config': config})
            assert saved() == config
            print('PASS: existing session stores and reloads changed model')
    finally:
        if session_id:
            request('DELETE', '/sessions/' + session_id + '?' + urlencode({'agent_id': agent_id}))
            print('Temporary test session removed; no chat or model request sent')
