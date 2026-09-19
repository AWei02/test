"""Authentication regression tests against an isolated portal store."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI, Request
import portal
from portal_auth import ensure_admin_key, new_key


class AuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(portal, 'FILE', Path(self.temp.name) / 'portal.json')
        self.patch.start()
        self.admin_key = ensure_admin_key()
        self.bob_key = new_key()
        data = portal.load()
        data['users'].append({'username': 'bob', 'email': '', 'role': '普通用户',
                              'enabled': True, 'login_key': self.bob_key})
        portal.save(data)
        app = FastAPI()
        app.state.storage = SimpleNamespace(**{name: AsyncMock(return_value=[]) for name in
            ('list_agents', 'list_mcps', 'list_skills', 'list_knowledge_bases', 'list_credentials')})

        @app.get('/health')
        async def identity(request: Request):
            return {'identity': request.headers.get('x-user-id')}

        @app.get('/workspace/files')
        async def signed_identity(request: Request):
            return {'identity': request.headers.get('x-user-id')}

        portal.install_portal(app)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()
        self.patch.stop()
        self.temp.cleanup()

    def auth(self, key=None):
        return {'Authorization': 'Bearer ' + (key or self.admin_key)}

    async def test_username_only_and_invalid_keys_rejected(self):
        for headers in ({}, {'x-user-id': portal.ADMIN}, self.auth('bad'), self.auth('x'*300)):
            response = await self.client.get('/portal/me', headers=headers)
            self.assertEqual(response.status_code, 401)

    async def test_identity_comes_from_key_and_me_never_leaks_key(self):
        response = await self.client.get('/portal/me', headers={**self.auth(self.bob_key), 'x-user-id': portal.ADMIN})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['username'], 'bob')
        self.assertFalse(response.json()['is_admin'])
        self.assertNotIn('login_key', response.json())
        response = await self.client.get('/health', headers={**self.auth(self.bob_key), 'x-user-id': portal.ADMIN})
        self.assertEqual(response.json()['identity'], 'bob')

    async def test_admin_can_repeatedly_view_rotate_and_preserve_key(self):
        for _ in range(2):
            response = await self.client.get('/portal/admin', headers=self.auth())
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(next(u for u in response.json()['users'] if u['username']=='bob')['login_key'], self.bob_key)
        response = await self.client.post('/portal/users/bob/key', headers=self.auth())
        self.assertEqual(response.status_code, 200)
        replacement = response.json()['login_key']
        self.assertNotEqual(replacement, self.bob_key)
        self.assertEqual((await self.client.get('/portal/me', headers=self.auth(self.bob_key))).status_code, 401)
        self.assertEqual((await self.client.get('/portal/me', headers=self.auth(replacement))).status_code, 200)
        response = await self.client.put('/portal/users', headers=self.auth(), json={
            'username':'bob','email':'new@example.com','role':'普通用户','enabled':True,'login_key':'injected'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(next(u for u in portal.load()['users'] if u['username']=='bob')['login_key'], replacement)
        self.assertEqual(ensure_admin_key(), self.admin_key)
        self.assertEqual(portal.FILE.stat().st_mode & 0o777, 0o600)

    async def test_non_admin_cannot_view_or_rotate_and_disabled_cannot_login(self):
        for method, path in [('GET','/portal/admin'),('POST','/portal/users/bob/key'),('POST',f'/portal/users/{portal.ADMIN}/key')]:
            response = await self.client.request(method,path,headers={**self.auth(self.bob_key),'x-user-id':portal.ADMIN})
            self.assertEqual(response.status_code,403,response.text)
        data=portal.load()
        next(u for u in data['users'] if u['username']=='bob')['enabled']=False
        portal.save(data)
        self.assertEqual((await self.client.get('/portal/me',headers=self.auth(self.bob_key))).status_code,401)

    async def test_configured_admin_alias_only(self):
        response = await self.client.get('/portal/me', headers=self.auth(portal.ADMIN))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['is_admin'])
        self.assertEqual((await self.client.get('/portal/me', headers=self.auth('bob'))).status_code, 401)
        data = portal.load()
        data['users'][0]['username'] = 'owner'
        portal.save(data)
        with patch.object(portal, 'ADMIN', 'owner'):
            self.assertEqual((await self.client.get('/portal/me', headers=self.auth('owner'))).status_code, 200)
            self.assertEqual((await self.client.get('/portal/me', headers=self.auth('wei'))).status_code, 401)

    async def test_signed_download_branch_strips_spoofed_identity(self):
        response=await self.client.get('/workspace/files?token=invalid',headers={'x-user-id':portal.ADMIN})
        self.assertIsNone(response.json()['identity'])


if __name__ == '__main__':
    unittest.main()
