"""Custom MCP API smoke test; starts only this local fixture, no external services."""
import sys

if '--serve' in sys.argv or '--serve-http' in sys.argv:
    from mcp.server.fastmcp import FastMCP
    server = FastMCP('portal-custom-fixture', host='127.0.0.1',
        port=int(sys.argv[-1]) if '--serve-http' in sys.argv else 8000)
    @server.tool()
    def echo(text: str) -> str:
        return text
    server.run(transport='streamable-http' if '--serve-http' in sys.argv else 'stdio')
else:
    import json
    import urllib.request
    import urllib.error
    from pathlib import Path
    from uuid import uuid4
    from custom_mcps import CustomMCPInput, make_client
    from fastapi import HTTPException

    BASE = 'http://127.0.0.1:5173/api/service'
    def request(method, path, body=None, user='wei', status=200):
        req = urllib.request.Request(BASE + path, method=method,
            headers={'X-User-ID': user, 'Content-Type': 'application/json'},
            data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=40) as response:
                code, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            code, raw = error.code, error.read()
        assert code == status, (path, code, raw[:500])
        return json.loads(raw) if raw else None

    name = 'custom-test-' + uuid4().hex[:8]
    user = 'mcp-test-' + uuid4().hex[:8]
    identifier = None
    http_process = None
    try:
        config = {'name': name, 'transport': 'stdio', 'command': sys.executable,
                  'args': [str(Path(__file__).resolve()), '--serve'], 'env': {}, 'enabled': True}
        identifier = request('POST', '/portal/custom-mcps', config)['id']
        result = request('POST', f'/portal/custom-mcps/{identifier}/test')
        assert result['tools'] == ['echo'], result
        import socket, subprocess, time
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        http_process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve-http', str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.1)
        request('PUT', f'/portal/custom-mcps/{identifier}', {'name': name, 'transport': 'http', 'url': f'http://127.0.0.1:{port}/mcp'})
        assert request('POST', f'/portal/custom-mcps/{identifier}/test')['tools'] == ['echo']
        request('POST', '/portal/custom-mcps', config, status=409)
        request('PUT', f'/portal/custom-mcps/{identifier}', {**config, 'description': 'edited', 'enabled': False})
        rows = request('GET', '/portal/custom-mcps')
        saved = next(r for r in rows if r['id'] == identifier)
        assert not saved['enabled'] and saved['description'] == 'edited'
        request('PUT', '/portal/users', {'username': user})
        request('GET', '/portal/custom-mcps', user=user, status=403)
        request('POST', '/portal/custom-mcps', config, user=user, status=403)
        request('POST', f'/portal/custom-mcps/{identifier}/test', user=user, status=403)
        for url in ('file:///etc/passwd', 'https://user:secret@example.com/mcp'):
            request('POST', '/portal/custom-mcps', {'name': name + '-bad', 'url': url}, status=400)
        http = make_client(CustomMCPInput(name='http-test', url='https://example.com/mcp', headers={'Authorization': 'Bearer fake'}))
        assert http.mcp_config.headers['Authorization'] == 'Bearer fake'
        sse = make_client(CustomMCPInput(name='sse-test', url='https://example.com/sse?key=fake'))
        assert sse._is_sse
        print('PASS: custom MCP create/edit/duplicate validation; real STDIO and HTTP connections list echo; SSE config; admin-only access.')
    finally:
        if http_process:
            http_process.terminate()
            http_process.wait(timeout=10)
        if identifier:
            request('DELETE', '/mcp/' + identifier, status=204)
        request('DELETE', '/portal/users/' + user)
