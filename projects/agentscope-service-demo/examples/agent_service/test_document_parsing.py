"""No paid provider calls, real documents or live MinIO are used here."""
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI, APIRouter, HTTPException
import portal
import document_parsing as p
from agentscope.app.storage import KnowledgeDocumentData, KnowledgeDocumentRecord


def bundle(entries=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as z:
        for name, value in (entries or {'full.md': '# Title\n\nBody', 'images/a.png': b'image'}).items():
            z.writestr(name, value)
    return output.getvalue()


class ParsingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(portal, 'FILE', Path(self.temp.name) / 'portal.json'); self.patch.start()
        self.env = patch.dict(os.environ, {'MINERU_LOCAL_URL': 'http://local:8001', 'MINERU_LOCAL_TOKEN': 'local-secret', 'MINERU_API_TOKEN': 'cloud-secret'})
        self.env.start()
        self.client = httpx.AsyncClient

    async def asyncTearDown(self):
        self.patch.stop(); self.env.stop(); self.temp.cleanup()

    def client_factory(self, handler):
        return lambda **kwargs: self.client(transport=httpx.MockTransport(handler), **kwargs)

    def test_heading_pages_code_and_zip_validation(self):
        sections = p.markdown_sections('<!-- page:2 -->\n# Title\nbody\n```\n# not heading\n```\n## Child\nnext','a.pdf')
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[1].metadata['heading_path'], ['Title','Child'])
        self.assertEqual(sections[0].metadata['page'], 2)
        self.assertIn('# not heading', sections[0].content.text)
        self.assertIn('images/a.png', p.unpack(bundle())[1])
        for entries in ({'../secret': 'x', 'full.md':'ok'}, {'one.md':'x','two.md':'y'}):
            with self.assertRaises(ValueError): p.unpack(bundle(entries))

    async def test_local_v1_complete_protocol_and_isolation(self):
        paths = []
        def handler(r):
            paths.append(r.url.path)
            self.assertEqual(r.headers.get('authorization'), 'Bearer local-secret')
            if r.url.path == '/v1/uploads': return httpx.Response(200, json={'id':'u','status':'pending','upload_url':'/v1/uploads/u/content','upload_method':'PUT'})
            if r.url.path.endswith('/complete'): return httpx.Response(200, json={'status':'completed','file':{'id':'f'}})
            if r.url.path.endswith('/content') and r.method == 'PUT': return httpx.Response(200)
            if r.url.path == '/v1/parse/jobs':
                self.assertNotIn('page_range', r.content.decode())
                return httpx.Response(200, json={'job_id':'j','status':'completed','files':[{'status':'completed','output_files':{'zip':{'file_id':'z'}}}]})
            return httpx.Response(200, content=bundle())
        with patch.object(p.httpx,'AsyncClient',self.client_factory(handler)):
            text, assets = await p.mineru_local(b'pdf','file.pdf',p.ParsingConfig())
        self.assertTrue(text.startswith('# Title')); self.assertEqual(len(paths),5)
        with patch.object(p.httpx,'AsyncClient',self.client_factory(lambda r: httpx.Response(200,json={
            'id':'u','status':'pending','upload_url':'https://external/upload'}))):
            with self.assertRaisesRegex(ValueError,'外部上传'):
                await p.mineru_local(b'pdf','file.pdf',p.ParsingConfig())

    async def test_cloud_upload_and_download_do_not_receive_key(self):
        def handler(r):
            if r.url.host == 'mineru.net':
                self.assertEqual(r.headers['authorization'],'Bearer cloud-secret')
                if r.method == 'POST': return httpx.Response(200,json={'code':0,'data':{'batch_id':'b','file_urls':['https://storage.example/upload']}})
                return httpx.Response(200,json={'code':0,'data':{'extract_result':[{'state':'done','full_zip_url':'https://storage.example/result'}]}})
            self.assertNotIn('authorization',r.headers)
            return httpx.Response(200,content=bundle() if r.method == 'GET' else b'')
        with patch.object(p.httpx,'AsyncClient',self.client_factory(handler)):
            text, _ = await p.mineru_cloud(b'pdf','x.pdf',p.ParsingConfig(mineru_mode='api'))
        self.assertIn('Body',text)

    async def test_llm_truncation_and_page_metadata(self):
        credentials = AsyncMock(return_value=({'api_key':'key'},'https://vision.example/v1',{'output_size':6000}))
        def handler(r):
            return httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':'partial'}}]})
        with patch.object(p,'llm_credentials',credentials), patch.object(p,'render_pages',return_value=[b'png']), patch.object(p.httpx,'AsyncClient',self.client_factory(handler)):
            with self.assertRaisesRegex(ValueError,'截断'):
                await p.visual_llm(b'pdf','x.pdf',p.ParsingConfig(engine='llm'),None,'wei')
        def complete(r): return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'# Heading\nBody'}}]})
        with patch.object(p,'llm_credentials',credentials), patch.object(p,'render_pages',return_value=[b'png',b'png']), patch.object(p.httpx,'AsyncClient',self.client_factory(complete)):
            text, images = await p.visual_llm(b'pdf','x.pdf',p.ParsingConfig(engine='llm'),None,'wei')
        self.assertIn('<!-- page:2 -->',text); self.assertEqual(len(images),2)

    async def test_direct_text_persists_private_artifact_without_cloud(self):
        doc = KnowledgeDocumentRecord(id='d',user_id='wei',knowledge_base_id='kb',processing_node='worker',status='parsing',
            data=KnowledgeDocumentData(filename='x.md',size=10,blob_uri='s3://bucket/source',access_mode='private'))
        storage = NS(get_knowledge_document=AsyncMock(return_value=doc), upsert_knowledge_document=AsyncMock())
        blobs = NS(write_stream=AsyncMock(return_value='s3://bucket/output'),delete=AsyncMock())
        with patch.object(p,'mineru_local',AsyncMock()) as local, patch.object(p,'mineru_cloud',AsyncMock()) as cloud:
            sections = await p.parse_document(doc,b'# Title\nBody',storage,blobs,None)
        local.assert_not_called(); cloud.assert_not_called()
        self.assertEqual(doc.data.access_mode,'private'); self.assertEqual(doc.status,'parsing')
        self.assertEqual(doc.data.parsing_result['engine'],'direct'); self.assertEqual(len(sections),1)
        self.assertNotIn('secret',str(doc.data.parsing_result))

    async def test_artifact_rechecks_parent_acl_and_hides_uris(self):
        app, router = FastAPI(), APIRouter()
        doc = KnowledgeDocumentRecord(id='d',user_id='wei',knowledge_base_id='kb',data=KnowledgeDocumentData(
            filename='x.md',size=1,blob_uri='s3://private/source', parsing_result={'artifacts':{'document.md':{'uri':'s3://private/output','size':1,'content_type':'text/markdown'}}}))
        service = NS(get_document=AsyncMock(side_effect=HTTPException(404)),_require_edit=AsyncMock())
        app.state.knowledge_base_service = service
        def admin(r):
            if r.headers.get('x-user-id') != 'wei': raise HTTPException(403)
        p.install_routes(router,app,admin,lambda r:r.headers.get('x-user-id')); app.include_router(router)
        async with self.client(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            response = await c.get('/parsing/kb/documents/d/artifact'); self.assertEqual(response.status_code,404)
            self.assertEqual((await c.patch('/parsing/kb',json=p.ParsingConfig().model_dump())).status_code,403)
            service.get_document.side_effect=None; service.get_document.return_value=doc
            response = await c.get('/parsing/kb/documents/d')
            self.assertEqual(response.status_code,200); self.assertNotIn('s3://',response.text)
            doc.status='ready';doc.data.stage_action='chunk';doc.data.chunk_count=62
            doc.data.chunk_draft={'version':'reset-v1','reset_from_index':True}
            response=await c.get('/parsing/kb/documents/d')
            self.assertFalse(response.json()['draft_pending'])
            self.assertTrue(response.json()['draft_editable'])
            doc.data.chunk_draft['manual_edits']=1
            response=await c.get('/parsing/kb/documents/d')
            self.assertTrue(response.json()['draft_pending'])

    async def test_invalid_config_and_office_llm_rejected(self):
        with self.assertRaises(HTTPException): await p.prepare(None,'wei','kb','a.pdf',{'engine':'bogus'})
        with self.assertRaises(HTTPException): await p.prepare(None,'wei','kb','a.docx',{'engine':'llm'})

    def test_real_pdf_render_bounds(self):
        from pypdf import PdfWriter
        writer=PdfWriter(); writer.add_blank_page(width=100,height=100); writer.add_blank_page(width=100,height=100)
        output=io.BytesIO(); writer.write(output)
        with self.assertRaisesRegex(ValueError,'上限'): p.render_pages(output.getvalue(),'two.pdf',1)
        self.assertEqual(len(p.render_pages(output.getvalue(),'two.pdf',2)),2)
