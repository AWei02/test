"""Regression: admin workspace MCP selection survives the next chat run."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import portal
from fastapi import HTTPException


class SelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_add_remove_persist_only_current_session(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(portal, 'FILE', Path(temp) / 'portal.json'):
            data = portal.load()
            key = portal.selection_key(portal.ADMIN, 'agent', 'current')
            data['selections'][key] = {'mcps': ['old'], 'skills': ['skill'], 'knowledge': ['kb']}
            portal.save(data)
            client = NS(name='web-search', mcp_config='config', is_stateful=True)
            record = NS(id='web', client=client, enabled=True)
            base = NS(add_mcp=AsyncMock(), remove_mcp=AsyncMock(), list_mcps=AsyncMock(return_value=[client]))
            storage = NS(get_mcp_by_name=AsyncMock(return_value=record), list_mcps=AsyncMock(return_value=[record]))
            ws = portal.PortalWorkspace(base, storage, portal.ADMIN, 'agent', 'current')
            await ws.add_mcp(client)
            self.assertEqual(ws.selected('mcps'), {'old', 'web'})
            self.assertEqual(portal.load()['selections'][key]['skills'], ['skill'])
            fresh = portal.PortalWorkspace(base, storage, portal.ADMIN, 'agent', 'current')
            self.assertEqual(await fresh.list_mcps(), [client])
            other = portal.PortalWorkspace(base, storage, portal.ADMIN, 'agent', 'other')
            self.assertEqual(await other.list_mcps(), [])
            await fresh.remove_mcp('web-search')
            self.assertEqual(await fresh.list_mcps(), [])
            self.assertEqual(fresh.selected('mcps'), {'old'})

    async def test_nonadmin_and_disabled_cannot_add(self):
        base = NS(add_mcp=AsyncMock())
        storage = NS(get_mcp_by_name=AsyncMock(return_value=NS(enabled=False)))
        ws = portal.PortalWorkspace(base, storage, 'member', 'a', 's')
        with self.assertRaises(HTTPException):
            await ws.add_mcp(NS(name='web-search'))
        ws = portal.PortalWorkspace(base, storage, portal.ADMIN, 'a', 's')
        with self.assertRaises(ValueError):
            await ws.add_mcp(NS(name='web-search'))
        base.add_mcp.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
