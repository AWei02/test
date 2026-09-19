"""Isolated tests: never access real user data or call models."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import FastAPI
import portal
from portal_auth import ensure_admin_key, new_key
import project_files as pf
import skill_packages as sp
import file_catalog as catalog


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [patch.object(portal, 'FILE', root/'portal.json'),
                        patch.object(pf, 'ROOT', root/'projects'), patch.object(sp, 'WORK', root/'sessions')]
        for p in self.patches: p.start()
        data = portal.load()
        self.bob_key = new_key()
        data['users'].append({'username':'bob','role':'reader','enabled':True,'login_key':self.bob_key})
        data['grants'].append({'id':'g','subject_type':'user','subject':'bob','agent_id':'a',
                               'mcps':[],'skills':[],'knowledge':[],'credentials':[]})
        data['projects']={'p': {'id':'p','owner':portal.ADMIN,'name':'private','shared':False}}
        portal.save(data)
        app = FastAPI()
        async def get_session(user, agent, session):
            return SimpleNamespace() if user == portal.ADMIN and agent == 'a' and session == 's' else None
        app.state.storage = SimpleNamespace(get_session=get_session)
        portal.install_portal(app)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'Authorization':'Bearer '+ensure_admin_key()})
        self.url='/portal/file-catalog/session/s'
        self.query={'agent_id':'a'}
        self.ws=SimpleNamespace(username=portal.ADMIN,agent='a',session='s')

    async def asyncTearDown(self):
        await self.client.aclose()
        for p in reversed(self.patches): p.stop()
        self.temp.cleanup()

    async def listing(self):
        response=await self.client.get(self.url,params=self.query)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['files']

    async def action(self, **body):
        return await self.client.post(self.url+'/action',params=self.query,json=body)

    async def test_upload_edit_derive_mark_restore_rename(self):
        r=await self.client.post('/portal/skill-files/a/s',files={'file':('budget.xlsx',b'original')})
        self.assertEqual(r.status_code,200,r.text)
        row=(await self.listing())[0]
        self.assertEqual(row['origin'],'uploaded');self.assertEqual(row['modified_by'],portal.ADMIN)
        directory=sp.workdir(portal.ADMIN,'a','s')
        # A binary skill edit preserves upload origin and captures each revision.
        async def execute(*args):
            (directory/'budget.xlsx').write_bytes(b'edited')
            (directory/'analysis.txt').write_text('result')
            return ('done',True)
        with patch.object(sp.RunSkill,'_execute',side_effect=execute):
            await sp.RunSkill(self.ws).execute('image','script.py',[],['budget.xlsx'])
        rows={r['name']:r for r in await self.listing()}
        self.assertEqual(rows['budget.xlsx']['origin'],'uploaded')
        self.assertEqual(rows['budget.xlsx']['version_count'],2)
        self.assertEqual(rows['analysis.txt']['origin'],'generated')
        self.assertEqual(rows['analysis.txt']['sources'][0]['id'],row['id'])
        self.assertEqual(rows['analysis.txt']['sources'][0]['version'],row['current_version'])
        r=await self.action(name='budget.xlsx',action='mark',is_result=True)
        self.assertEqual(r.status_code,200)
        r=await self.action(name='budget.xlsx',action='restore',version=row['current_version'],expected_version=row['current_version'],confirmed=True)
        self.assertEqual(r.status_code,409)
        current=rows['budget.xlsx']
        r=await self.action(name='budget.xlsx',action='restore',version=row['current_version'],expected_version=current['current_version'],confirmed=True)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual((directory/'budget.xlsx').read_bytes(),b'original')
        row=next(r for r in await self.listing() if r['name']=='budget.xlsx')
        self.assertEqual(row['version_count'],3);self.assertTrue(row['is_result'])
        r=await self.action(name='budget.xlsx',action='rename',new_name='renamed.xlsx',expected_version=row['current_version'],confirmed=True)
        self.assertEqual(r.status_code,200,r.text)
        renamed=next(r for r in await self.listing() if r['name']=='renamed.xlsx')
        self.assertEqual(renamed['id'],row['id']);self.assertEqual(renamed['origin'],'uploaded')
        self.assertTrue(renamed['is_result']);self.assertEqual(renamed['version_count'],3)
        r=await self.client.get(self.url+'/download',params={**self.query,'name':'renamed.xlsx','version':current['current_version']})
        self.assertEqual(r.content,b'edited')

    async def test_text_tool_sources_legacy_and_failure_tracking(self):
        directory=sp.workdir(portal.ADMIN,'a','s')
        (directory/'legacy.txt').write_text('old')
        legacy=(await self.listing())[0]
        self.assertEqual(legacy['origin'],'unknown')
        result=await pf.ProjectFiles(self.ws).call('write',name='new.txt',content='new',source_names=['legacy.txt'])
        self.assertEqual(result.state.value,'success')
        result=await pf.ProjectFiles(self.ws).call('write',name='new.txt',content='newer')
        self.assertEqual(result.state.value,'success')
        rows={r['name']:r for r in await self.listing()}
        self.assertEqual(rows['new.txt']['version_count'],2)
        self.assertEqual(rows['new.txt']['origin'],'generated')
        self.assertEqual(rows['new.txt']['sources'][0]['id'],legacy['id'])
        result=await pf.ProjectFiles(self.ws).call('write',name='bad.txt',content='bad',source_names=['missing.txt'])
        self.assertEqual(result.state.value,'error');self.assertFalse((directory/'bad.txt').exists())
        async def failing(*args):
            (directory/'partial.txt').write_text('partial')
            raise RuntimeError('failure')
        with patch.object(sp.RunSkill,'_execute',side_effect=failing), self.assertRaises(RuntimeError):
            await sp.RunSkill(self.ws).execute('image','script.py',[])
        rows={r['name']:r for r in await self.listing()}
        self.assertEqual(rows['partial.txt']['origin'],'generated')
        self.assertFalse(rows['partial.txt']['is_result'])

    async def test_permissions_paths_and_private_project(self):
        await self.client.post('/portal/skill-files/a/s',files={'file':('file.txt',b'original')})
        for url in (self.url,self.url+'/history',self.url+'/download'):
            response=await self.client.get(url,params={**self.query, 'name':'file.txt'},headers={'Authorization':'Bearer '+self.bob_key})
            self.assertEqual(response.status_code,404)
        r=await self.client.get('/portal/file-catalog/project/p',headers={'Authorization':'Bearer '+self.bob_key})
        self.assertEqual(r.status_code,404)
        for name in ('../portal.json','/etc/passwd'):
            r=await self.client.get(self.url+'/download',params={**self.query,'name':name})
            self.assertEqual(r.status_code,400)
        r=await self.client.get(self.url+'/download',params={**self.query,'name':'file.txt','version':'../../portal.json'})
        self.assertEqual(r.status_code,404)
        r=await self.client.post('/portal/projects/p/files',files={'file':('project.pdf',b'pdf')})
        self.assertEqual(r.status_code,200,r.text)
        r=await self.client.get('/portal/file-catalog/project/p')
        self.assertEqual(r.json()['files'][0]['origin'],'uploaded')
        r=await self.client.post('/portal/skill-files/a/s',files={'file':('file.txt',b'overwrite')})
        self.assertEqual(r.status_code,409)
        self.assertEqual((sp.workdir(portal.ADMIN,'a','s')/'file.txt').read_bytes(),b'original')


if __name__=='__main__': unittest.main()
