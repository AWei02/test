"""Offline runtime checks: python -m unittest test_portal -v."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import portal
from agentscope.app.access import ResourceKind
from fastapi import HTTPException


class PortalRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_knowledge_delete_checks_grants_before_service_mutation(self):
        import httpx
        from fastapi import FastAPI
        from agentscope.app._router._knowledge_base import knowledge_base_router
        from agentscope.app.deps import get_current_user_id, get_knowledge_base_service
        app=FastAPI(); app.state.resource_access_policy=portal.PortalPolicy()
        service=SimpleNamespace(_require_edit=AsyncMock(return_value=portal.ADMIN),delete_knowledge_base=AsyncMock())
        app.dependency_overrides[get_current_user_id]=lambda:portal.ADMIN
        app.dependency_overrides[get_knowledge_base_service]=lambda:service
        app.include_router(knowledge_base_router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            data=portal.load();data['grants'][1]['knowledge']=['k1'];portal.save(data)
            response=await client.delete('/knowledge_bases/k1')
            self.assertEqual(response.status_code,409)
            self.assertIn('a',response.json()['detail']);self.assertIn('b',response.json()['detail'])
            service.delete_knowledge_base.assert_not_awaited()
            data['grants'][0]['knowledge']=[];portal.save(data)
            self.assertEqual((await client.delete('/knowledge_bases/k1')).status_code,409)
            service.delete_knowledge_base.assert_not_awaited()
            data['grants'][1]['knowledge']=[];portal.save(data)
            self.assertEqual((await client.delete('/knowledge_bases/k1')).status_code,204)
            service.delete_knowledge_base.assert_awaited_once_with(portal.ADMIN,'k1')

    async def test_mcp_skill_delete_protects_user_and_role_grants(self):
        import httpx
        from fastapi import FastAPI
        from agentscope.app._router._mcp import mcp_router
        from agentscope.app._router._skill import skill_router
        from agentscope.app.deps import get_storage, get_current_user_id
        app=FastAPI()
        storage=SimpleNamespace(get_mcp=AsyncMock(return_value=object()),get_skill=AsyncMock(return_value=object()),
            delete_mcp=AsyncMock(return_value=True),delete_skill=AsyncMock(return_value=True))
        app.state.resource_access_policy=portal.PortalPolicy()
        app.dependency_overrides[get_storage]=lambda:storage
        app.dependency_overrides[get_current_user_id]=lambda:portal.ADMIN
        app.include_router(mcp_router);app.include_router(skill_router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            for kind, resource, grant in [('mcp','m1','a'),('skill','s1','a'),('skill','s2','b')]:
                response=await client.delete(f'/{kind}/{resource}')
                self.assertEqual(response.status_code,409)
                self.assertIn(grant,response.json()['detail'])
            storage.delete_mcp.assert_not_awaited();storage.delete_skill.assert_not_awaited()
            # Disabled subjects still own grants until explicitly revoked.
            data=portal.load();data['users'][1]['enabled']=False;portal.save(data)
            self.assertEqual((await client.delete('/mcp/m1')).status_code,409)
            data['grants']=[];portal.save(data)
            self.assertEqual((await client.delete('/mcp/m1')).status_code,204)
            self.assertEqual((await client.delete('/skill/s2')).status_code,204)
            storage.delete_mcp.assert_awaited_once_with(portal.ADMIN,'m1')
            storage.delete_skill.assert_awaited_once_with(portal.ADMIN,'s2')
            storage.get_skill.return_value=None
            self.assertEqual((await client.delete('/skill/missing')).status_code,404)
            storage.delete_skill.assert_awaited_once()

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = patch.object(portal, 'FILE', Path(self.temp.name) / 'portal.json')
        self.path.start()
        data = portal.load()
        data['users'] += [{'username': u, 'email': '', 'role': 'reader', 'enabled': True}
                          for u in ('alice', 'bob')]
        data['grants'] = [dict(id='a', subject_type='user', subject='alice', agent_id='agent',
            mcps=['m1'], skills=['s1'], knowledge=['k1'], credentials=['c1']),
            dict(id='b', subject_type='role', subject='reader', agent_id='agent',
            mcps=[], skills=['s2'], knowledge=[], credentials=[])]
        data['selections'][portal.selection_key('alice', 'agent', 'session')] = {
            'mcps': ['m1', 'm2'], 'skills': ['s1', 's2', 's3'], 'knowledge': ['k1']}
        portal.save(data)

    async def asyncTearDown(self):
        self.path.stop()
        self.temp.cleanup()

    async def test_role_and_user_grants_merge(self):
        grant = portal.grant_for('alice', 'agent')
        self.assertEqual(grant['skills'], ['s1', 's2'])
        self.assertEqual(portal.grant_for('bob', 'agent')['credentials'], [])
        refs = await portal.PortalPolicy().list_accessible('alice', ResourceKind.KNOWLEDGE_BASE, None)
        self.assertEqual([r.resource_id for r in refs], ['k1'])
        self.assertEqual(refs[0].permission, 'read')

    async def test_runtime_filters_and_revocation(self):
        storage = SimpleNamespace(list_skills=AsyncMock(return_value=[
            SimpleNamespace(id='s1', enabled=True, name='allowed', description='test', markdown='Answer with ALLOWED'),
            SimpleNamespace(id='s2', enabled=False, name='disabled', description='', markdown=''),
            SimpleNamespace(id='s3', enabled=True, name='forbidden', description='', markdown='')]))
        ws = portal.PortalWorkspace(SimpleNamespace(workdir=self.temp.name), storage, 'alice', 'agent', 'session')
        self.assertEqual([s.name for s in await ws.list_skills()], ['allowed'])
        self.assertEqual(ws.selected('mcps'), {'m1'})
        data = portal.load()
        data['grants'][0]['mcps'] = []
        portal.save(data)
        self.assertEqual(ws.selected('mcps'), set())
        self.assertEqual([t.name for t in await ws.list_tools()], ['ProjectFiles'])
        rag_type = type('RagSearch', (), {'__module__': 'agentscope.middleware._rag', 'name': 'search_knowledge'})
        tools, groups = ws.filter_tool_access([SimpleNamespace(name='Bash'),
            SimpleNamespace(name='AgentCreate'), rag_type()], ['schedule'])
        self.assertEqual([t.name for t in tools], ['search_knowledge'])
        self.assertEqual(groups, [])

    async def test_workspace_users_and_sessions_are_isolated(self):
        manager = portal.PortalWorkspaceManager(basedir=self.temp.name)
        manager.bind_storage(SimpleNamespace(get_session=AsyncMock(return_value=None)))
        try:
            a = await manager.get_workspace('alice', 'agent', 'session')
            b = await manager.get_workspace('bob', 'agent', 'session')
            c = await manager.get_workspace('alice', 'agent', 'another')
            self.assertEqual(len({a.workdir, b.workdir, c.workdir}), 3)
            self.assertEqual(await a.base.list_mcps(agent_id='agent', session_id='session'), [])
        finally:
            await manager.close_all()

    async def test_disabled_user_denied_after_login(self):
        data = portal.load()
        next(u for u in data['users'] if u['username'] == 'alice')['enabled'] = False
        portal.save(data)
        with self.assertRaises(HTTPException):
            portal.grant_for('alice', 'agent')


if __name__ == '__main__':
    unittest.main()
