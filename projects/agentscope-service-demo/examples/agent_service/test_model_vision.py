"""Offline capability round-trip checks with isolated portal storage."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
import portal


class ModelVisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_capability_roundtrip_and_validation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            portal, 'FILE', Path(directory) / 'portal.json',
        ):
            data = portal.load()
            name = 'deepseek-v4-flash-vision'
            data['official_models'] = {'local': {
                'models': [name], 'fetched_at': None, 'selection_initialized': True,
                'enabled_models': [], 'model_types': {}, 'model_configs': {},
            }}
            portal.save(data)
            app = FastAPI()
            app.state.resource_access_service = SimpleNamespace(
                resolve_credential=AsyncMock(return_value=SimpleNamespace(data={
                    'type': 'openai_credential', 'api_key': 'test-only',
                    'base_url': 'http://localhost:8001/v1',
                })),
            )
            portal.install_portal(app)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://test',
                headers={'x-user-id': portal.ADMIN},
            ) as client:
                url = '/portal/models/local'
                response = await client.get(url)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertNotIn('image/*', response.json()['models'][0]['input_types'])
                for vision in (True, False):
                    payload = {'enabled_models': [name], 'model_types': {name: 'llm'},
                               'model_configs': {name: {'context_size': 8192,
                                                       'output_size': 1024,
                                                       'vision': vision}}}
                    response = await client.put(url + '/enabled', json=payload)
                    self.assertEqual(response.status_code, 200, response.text)
                    response = await client.get(url)
                    result = response.json()
                    self.assertEqual('image/*' in result['models'][0]['input_types'], vision)
                    self.assertEqual(result['model_configs'][name]['vision'], vision)
                    self.assertEqual(result['enabled_models'], [name])
                payload['model_configs'][name]['vision'] = 'true'
                response = await client.put(url + '/enabled', json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(portal.load()['official_models']['local']['model_configs'][name]['vision'])


if __name__ == '__main__':
    unittest.main()
