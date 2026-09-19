import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import patch, AsyncMock
from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.testclient import TestClient
import portal
from channel_audit import install_routes
from project_files import member_key

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.patch=patch.object(portal,'FILE',Path(self.tmp.name)/'portal.json');self.patch.start()
        data=portal.load();data['projects']={'p':{'id':'p','name':'P','owner':portal.ADMIN},'other':{'id':'other','name':'Other','owner':portal.ADMIN}}
        data['project_sessions']={member_key(portal.ADMIN,'a','s'):'p'};portal.save(data)
        self.record=NS(id='s',agent_id='a',config=NS(name='channel-chat'),origin=NS(channel_id='c',chat_id='group',chat_name='Group',channel_user_id='external-user'),created_at=datetime.now(),updated_at=datetime.now())
        self.storage=NS(list_channels=AsyncMock(return_value=[NS(id='c',name='Channel',channel_type='feishu',session=NS(project_id='p'))]),list_sessions_by_channel=AsyncMock(return_value=[self.record]),get_session=AsyncMock(return_value=self.record),list_messages=AsyncMock(return_value=([{'id':'m','role':'user','content':[{'type':'text','text':'audit message'}]}],True)))
        app=FastAPI();app.state.storage=self.storage;router=APIRouter(prefix='/portal')
        def admin(request):
            if request.headers.get('x-user-id')!=portal.ADMIN:raise HTTPException(403,'admin only')
        install_routes(router,app,admin);app.include_router(router);self.client=TestClient(app);self.headers={'X-User-ID':portal.ADMIN}
    def tearDown(self):self.client.close();self.patch.stop();self.tmp.cleanup()
    def test_list_and_read(self):
        result=self.client.get('/portal/projects/p/channel-records',headers=self.headers)
        self.assertEqual(result.status_code,200);self.assertEqual(len(result.json()),1)
        self.assertEqual(result.json()[0]['channel_user_id'],'external-user')
        result=self.client.get('/portal/projects/p/channel-records/a/s/messages?before=m2',headers=self.headers)
        self.assertEqual(result.status_code,200);self.assertEqual(result.json()['messages'][0]['content'][0]['text'],'audit message')
        self.storage.list_messages.assert_awaited_once_with(portal.ADMIN,'s',limit=100,before='m2')
    def test_non_admin_denied_both_endpoints(self):
        for path in ('','/a/s/messages'):
            self.assertEqual(self.client.get('/portal/projects/p/channel-records'+path,headers={'X-User-ID':'ordinary'}).status_code,403)
        self.storage.list_messages.assert_not_awaited()
    def test_other_project_denied(self):
        self.assertEqual(self.client.get('/portal/projects/other/channel-records/a/s/messages',headers=self.headers).status_code,404)
    def test_deleted_channel_and_no_web_chat_leak(self):
        self.storage.list_channels.return_value=[]
        r=self.client.get('/portal/projects/p/channel-records',headers=self.headers)
        self.assertEqual(r.json()[0]['channel_name'],'已删除频道')
        self.record.origin=NS(type='user')
        self.assertEqual(self.client.get('/portal/projects/p/channel-records',headers=self.headers).json(),[])

if __name__=='__main__':unittest.main()
