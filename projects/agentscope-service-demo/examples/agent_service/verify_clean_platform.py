"""Read-only API checks for the freshly reset platform, plus a temporary vector probe."""
import asyncio
from fastapi.testclient import TestClient
from main import app
from portal import load, ADMIN
from verify_storage import vectors

if __name__ == '__main__':
    data = load()
    assert len(data['users']) == 1 and data['users'][0]['username'] == ADMIN
    assert not data['grants'] and not data.get('projects')
    asyncio.run(vectors())
    with TestClient(app) as client:
        for path in ('/health', '/agent', '/portal/projects', '/credential'):
            response = client.get(path, headers={'x-user-id': ADMIN})
            assert response.status_code == 200, (path, response.status_code)
            print(path, response.json())
    print('PASS: clean platform startup and APIs')
