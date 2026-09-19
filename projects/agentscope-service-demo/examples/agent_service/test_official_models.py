"""Offline regression tests; never send a real API key."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from agentscope.app._router._credential import refresh_official_models


class OfficialModelsTests(unittest.IsolatedAsyncioTestCase):
    async def query(self, response=None, base='https://api.deepseek.com', denied=False,
                    credential_type='deepseek_credential', expect_request=True):
        access = SimpleNamespace(resolve_for_edit=AsyncMock(
            side_effect=HTTPException(403, 'denied') if denied else None,
            return_value=('wei', None),
        ))
        data = {'type': credential_type, 'base_url': base, 'api_key': 'test-only'}
        storage = SimpleNamespace(get_credential=AsyncMock(
            return_value=SimpleNamespace(model_dump=lambda: {'data': data}),
        ))
        with patch('agentscope.app._router._credential.httpx.AsyncClient') as factory:
            client = factory.return_value.__aenter__.return_value
            client.get = AsyncMock(return_value=response)
            try:
                return await refresh_official_models('test', 'wei', storage, access)
            finally:
                if denied or not expect_request or (
                    credential_type == 'deepseek_credential'
                    and base != 'https://api.deepseek.com'
                ):
                    client.get.assert_not_called()

    async def test_live_ids_are_not_hardcoded(self):
        result = await self.query(httpx.Response(200, json={'data': [
            {'id': 'new-future-model'}, {'id': 'deepseek-flash'}, {'id': 'deepseek-flash'},
        ]}))
        self.assertEqual(result['models'], ['deepseek-flash', 'new-future-model'])
        self.assertIn('fetched_at', result)
        self.assertNotIn('test-only', str(result))

    async def test_upstream_errors_and_invalid_payload(self):
        for response, status in [(httpx.Response(401), 400), (httpx.Response(429), 429),
                                 (httpx.Response(503), 502),
                                 (httpx.Response(200, json={'data': None}), 502)]:
            with self.assertRaises(HTTPException) as caught:
                await self.query(response)
            self.assertEqual(caught.exception.status_code, status)

    async def test_other_hosts_never_receive_key(self):
        with self.assertRaises(HTTPException) as caught:
            await self.query(base='https://example.org')
        self.assertEqual(caught.exception.status_code, 400)

    async def test_local_openai_http_models(self):
        for base in ('http://192.168.0.10:8000/v1', 'http://localhost:8000/v1',
                     'http://[::1]:8000/v1', 'https://example.org/v1'):
            result = await self.query(
                httpx.Response(200, json={'data': [{'id': 'local-vision'}]}),
                base=base, credential_type='openai_credential',
            )
            self.assertEqual(result['models'], ['local-vision'])
            self.assertEqual(result['source'], base + '/models')

    async def test_invalid_openai_schemes_never_receive_key(self):
        for base in ('ftp://localhost/v1', 'file:///tmp/models',
                     'http:///v1', 'http://:8000/v1'):
            with self.assertRaises(HTTPException) as caught:
                await self.query(base=base, credential_type='openai_credential',
                                 expect_request=False)
            self.assertEqual(caught.exception.status_code, 400)

    async def test_deepseek_official_still_rejects_http(self):
        with self.assertRaises(HTTPException) as caught:
            await self.query(base='http://api.deepseek.com')
        self.assertEqual(caught.exception.status_code, 400)

    async def test_edit_permission_required(self):
        with self.assertRaises(HTTPException) as caught:
            await self.query(denied=True)
        self.assertEqual(caught.exception.status_code, 403)


if __name__ == '__main__':
    unittest.main()
