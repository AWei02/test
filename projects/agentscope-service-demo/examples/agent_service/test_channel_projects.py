"""Offline channel scoping regressions. No platform connections or model calls."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
import portal, project_files
from channel_projects import prepare, validate
from skill_packages import workdir
from agentscope.app.storage import SessionSettings, SessionConfig

class ChannelProjectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(portal,'FILE',Path(self.tmp.name)/'data.json'), patch.object(project_files,'ROOT',Path(self.tmp.name)/'files')]
        for p in self.patches:p.start()
        data=portal.load()
        data['projects']={'p':{'id':'p','owner':portal.ADMIN,'agent_id':'agent','name':'P','shared':False}}
        portal.save(data)
        self.catalog={'mcps':[{'id':'m','name':'M'}],'skills':[{'id':'s','name':'S'}],'knowledge':[{'id':'k','name':'K'}]}
        self.catpatch=patch.object(portal,'catalog',AsyncMock(return_value=self.catalog));self.catpatch.start()
        self.record=NS(id='ch',user_id=portal.ADMIN,session=SessionSettings(project_id='p',chat_model_config={}))
        self.storage=NS(get_session=AsyncMock(return_value=NS(origin=NS(channel_id='ch'))),get_channel=AsyncMock(return_value=self.record),list_skills=AsyncMock(return_value=[]),list_mcps=AsyncMock(return_value=[]))
    async def asyncTearDown(self):
        self.catpatch.stop()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    async def test_default_all_shared_directory_and_serialization(self):
        selected=await prepare(self.storage,self.record,'agent','one')
        self.assertEqual(selected,{'mcps':['m'],'skills':['s'],'knowledge':['k']})
        await prepare(self.storage,self.record,'agent','two')
        self.assertEqual(workdir(portal.ADMIN,'agent','one'),workdir(portal.ADMIN,'agent','two'))
        self.assertEqual(SessionSettings.model_validate_json(self.record.session.model_dump_json()).project_id,'p')
    async def test_empty_selection_does_not_restore_admin_tools(self):
        self.record.session.capabilities={'mcps':[],'skills':[],'knowledge':[]}
        manager=portal.PortalWorkspaceManager(basedir=self.tmp.name+'/workspaces');manager.bind_storage(self.storage)
        try:
            ws=await manager.get_workspace(portal.ADMIN,'agent','one')
            self.assertEqual(ws.selected('skills'),set())
            self.assertEqual(await ws.list_mcps(),[])
            self.assertEqual(await ws.list_skills(),[])
            self.assertEqual([t.name for t in await ws.list_tools()],['ProjectFiles'])
            self.assertEqual(ws.filter_tool_access([NS(name='Bash')],['schedule']),([],[]))
            result=await (await ws.list_tools())[0].call('write',name='test.txt',content='CHANNEL')
            self.assertEqual(result.state.value,'success')
            self.assertEqual((workdir(portal.ADMIN,'agent','one')/'test.txt').read_text(),'CHANNEL')
            self.record.session.capabilities={'mcps':['m'],'skills':['s'],'knowledge':[]}
            next_ws=await manager.get_workspace(portal.ADMIN,'agent','one')
            self.assertEqual(next_ws.selected('skills'),{'s'})
            self.assertIsNot(next_ws.base,ws.base)
        finally:await manager.close_all()
    async def test_invalid_project_agent_resources_and_deleted_project(self):
        with self.assertRaises(HTTPException):await validate(self.storage,portal.ADMIN,{'project_id':'p'},[{'agent_id':'wrong'}])
        with self.assertRaises(HTTPException):await validate(self.storage,portal.ADMIN,{'project_id':'p','capabilities':{'mcps':['missing'],'skills':[],'knowledge':[]}},[{'agent_id':'agent'}])
        data=portal.load();data['projects']['p']['deleted']=True;portal.save(data)
        with self.assertRaises(HTTPException):await prepare(self.storage,self.record,'agent','one')
    async def test_gateway_updates_existing_knowledge_selection(self):
        from agentscope.app.channel._gateway import ChannelGateway
        gateway=ChannelGateway.__new__(ChannelGateway)
        manager=portal.PortalWorkspaceManager(basedir=self.tmp.name);manager.bind_storage(self.storage)
        gateway._workspace_manager=manager
        gateway._storage=NS(get_session=AsyncMock(return_value=NS(config=SessionConfig(workspace_id='test'))),upsert_session=AsyncMock())
        await gateway._ensure_session(self.record,'agent','one',None,None)
        config=gateway._storage.upsert_session.call_args.args[2]
        self.assertEqual(config.knowledge_config.knowledge_base_ids,['k'])
        self.record.session.capabilities={'mcps':[],'skills':[],'knowledge':[]}
        await gateway._ensure_session(self.record,'agent','one',None,None)
        self.assertIsNone(gateway._storage.upsert_session.call_args.args[2].knowledge_config)

if __name__=='__main__':unittest.main()
