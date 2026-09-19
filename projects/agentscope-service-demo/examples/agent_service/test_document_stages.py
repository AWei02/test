import io
import json
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import FastAPI, APIRouter, HTTPException
from agentscope.app.storage import KnowledgeDocumentData, KnowledgeDocumentRecord
from agentscope.rag import ApproxTokenChunker
import document_stages as stages

class StageTests(unittest.IsolatedAsyncioTestCase):
    def test_restore_deleted_block_preserves_previous_color_and_parent(self):
        from document_chunking import build_chunks, ChunkingConfig
        for previous in (None, 'modified'):
            chunks=build_chunks('first\nsecond', 't', ChunkingConfig(mode='parent_child'))
            if previous: chunks[0].metadata['draft_change']=previous
            rows=[c.model_dump(mode='json') for c in chunks]
            deleted=stages.edit_chunks(rows,stages.DraftEdit(version='v',action='delete',chunk_index=0))
            self.assertEqual(deleted[0].metadata['draft_change'],'deleted')
            self.assertNotIn('first',deleted[1].metadata['parent_text'])
            restored=stages.edit_chunks([c.model_dump(mode='json') for c in deleted],stages.DraftEdit(version='v',action='restore',chunk_index=0))
            self.assertEqual(restored[0].metadata.get('draft_change'),previous)
            self.assertNotIn('draft_before_delete',restored[0].metadata)
            self.assertIn('first',restored[1].metadata['parent_text'])
            with self.assertRaises(HTTPException):
                stages.edit_chunks([c.model_dump(mode='json') for c in restored],stages.DraftEdit(version='v',action='restore',chunk_index=0))

    def test_added_block_delete_removes_it_even_after_edit(self):
        from document_chunking import build_chunks, ChunkingConfig
        chunks=build_chunks('first\nsecond', 't', ChunkingConfig(mode='parent_child'))
        def edit(chunks, action, index, text=''):
            return stages.edit_chunks([c.model_dump(mode='json') for c in chunks],stages.DraftEdit(version='v',action=action,chunk_index=index,text=text))
        for position in (-1,0,1):
            added=edit(chunks,'insert',position,'new block')
            changed=edit(added,'edit',position+1,'edited new block')
            self.assertEqual(changed[position+1].metadata['draft_change'],'added')
            remaining=edit(changed,'delete',position+1)
            self.assertEqual([c.content.text for c in remaining],['first','second'])
            self.assertEqual([c.chunk_index for c in remaining],[0,1])
            self.assertTrue(all(c.total_chunks==2 and c.metadata.get('draft_change') != 'deleted' for c in remaining))
            self.assertTrue(all('edited new block' not in c.metadata['parent_text'] for c in remaining))

    async def test_indexed_preview_preserves_ready_index_and_editable_draft(self):
        from document_chunking import ChunkingConfig
        self.doc.status='ready';self.doc.data.chunk_count=62
        self.doc.data.parsing_result={'version':'p1','artifacts':{'document.md':{'uri':'md'}}}
        self.doc.data.confirmed_parsing_version='p1'
        self.doc.data.confirmed_chunks_version='indexed-v1'
        async def lease(owner,kb,doc,node,duration):
            self.doc.processing_node=node
            return True
        self.storage.acquire_knowledge_document_lease.side_effect=lease
        app,router=FastAPI(),APIRouter();app.state.storage=self.storage;app.state.blob_store=self.blobs
        from document_chunking import build_chunks
        indexed = build_chunks('indexed\n'*62, 't', ChunkingConfig())
        app.state.knowledge_base_service=NS(get_document=AsyncMock(return_value=self.doc),_require_edit=AsyncMock(),_bus=None,
            list_document_chunks=AsyncMock(return_value=(indexed,62)))
        stages.install_routes(router,app,lambda r:None,lambda r:'owner');app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            path='/parsing/kb/documents/doc'
            reset=await c.post(path+'/draft/reset')
            self.assertEqual(reset.status_code,200)
            restored=json.loads(self.files[self.doc.data.chunk_draft['uri']])
            self.assertEqual(len(restored),62)
            self.assertTrue(all(r['content']['text']=='indexed' and 'draft_change' not in r['metadata'] for r in restored))
            self.assertEqual(self.doc.status,'ready')
            with patch.object(stages,'enqueue_index_task',new=AsyncMock()) as enqueue:
                response=await c.post(path+'/advance',json={'action':'chunk','version':'p1','config':ChunkingConfig().model_dump()})
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json()['status'],'ready')
                self.assertEqual(self.doc.status,'ready');self.assertEqual(self.doc.data.chunk_count,62)
                enqueue.assert_not_awaited();self.manager.get_knowledge.assert_not_called()
                self.knowledge.delete_document.assert_not_awaited();self.knowledge.insert_document.assert_not_awaited()
                version=self.doc.data.chunk_draft['version']
                response=await c.patch(path+'/draft',json={'version':version,'action':'edit','chunk_index':0,'text':'Updated draft only'})
                self.assertEqual(response.status_code,200);self.assertEqual(self.doc.status,'ready')
                self.assertEqual(self.doc.data.chunk_count,62)
                version=response.json()['version']
                with patch.object(stages,'build_review_draft',new=AsyncMock(side_effect=ValueError('Invalid preview'))):
                    failed=await c.post(path+'/advance',json={'action':'chunk','version':'p1'})
                self.assertEqual(failed.status_code,422)
                self.assertEqual(self.doc.data.chunk_draft['version'],version)
                self.assertEqual(self.doc.status,'ready')
                response=await c.post(path+'/advance',json={'action':'embed','version':version,'config':ChunkingConfig().model_dump()})
                self.assertEqual(response.status_code,200);enqueue.assert_awaited_once()
                self.assertEqual(self.doc.status,'pending')

    async def asyncSetUp(self):
        self.doc=KnowledgeDocumentRecord(id='doc',user_id='owner',knowledge_base_id='kb',status='pending',processing_node='worker',
            data=KnowledgeDocumentData(filename='test.md',size=3,blob_uri='raw',manual_stages=True))
        self.files={'md':b'# Title\n\nOne paragraph.\n\n## Next\n\nSecond paragraph.'}
        @asynccontextmanager
        async def opened(uri): yield NS(read=AsyncMock(return_value=self.files[uri]))
        async def write(key,stream): self.files[key]=stream.read(); return key
        self.blobs=NS(open=opened,write_stream=AsyncMock(side_effect=write))
        async def status(owner,kb,doc,value,**kwargs):
            self.doc.status=value
            for k,v in kwargs.items(): setattr(self.doc.data,k,v)
        self.storage=NS(get_knowledge_document=AsyncMock(side_effect=lambda *a:self.doc),upsert_knowledge_document=AsyncMock(),
            update_knowledge_document_status=AsyncMock(side_effect=status),acquire_knowledge_document_lease=AsyncMock(return_value=True),
            release_knowledge_document_lease=AsyncMock())
        self.knowledge=NS(delete_document=AsyncMock(),insert_document=AsyncMock())
        self.manager=NS(get_knowledge_base=AsyncMock(),get_knowledge=AsyncMock(return_value=self.knowledge))
        self.worker=NS(_storage=self.storage,_blob_store=self.blobs,_manager=self.manager,
            _read_blob=AsyncMock(return_value=b'raw'),_resource_access_service=None,_resolve_chunker_from_record=lambda r:ApproxTokenChunker())

    async def test_stages_stop_and_embed_exact_confirmed_draft(self):
        async def parse(*args): self.doc.data.parsing_result={'version':'v1','artifacts':{'document.md':{'uri':'md'}}}
        with patch.object(stages,'parse_document',side_effect=parse): await stages.process_stage(self.doc,self.worker)
        self.assertEqual(self.doc.status,stages.WAIT_PARSE); self.manager.get_knowledge.assert_not_called()
        self.doc.data.stage_action='chunk'
        with self.assertRaisesRegex(ValueError,'确认'): await stages.process_stage(self.doc,self.worker)
        self.doc.data.confirmed_parsing_version='v1'
        await stages.process_stage(self.doc,self.worker)
        self.assertEqual(self.doc.status,stages.WAIT_CHUNKS); self.manager.get_knowledge.assert_not_called()
        self.doc.data.stage_action='embed'
        with self.assertRaisesRegex(ValueError,'确认'): await stages.process_stage(self.doc,self.worker)
        self.doc.data.confirmed_chunks_version=self.doc.data.chunk_draft['version']
        reviewed=json.loads(self.files[self.doc.data.chunk_draft['uri']])
        self.files['md']=b'Changed after review; must NOT be silently re-chunked.'
        operations=[]
        self.knowledge.delete_document.side_effect=lambda doc: operations.append(('delete',doc))
        self.knowledge.insert_document.side_effect=lambda **kw: operations.append(('insert',kw['document_id']))
        await stages.process_stage(self.doc,self.worker)
        self.assertEqual(operations,[('delete','doc'),('insert','doc')])
        self.assertEqual(self.doc.status,'ready')
        actual=self.knowledge.insert_document.call_args.kwargs['chunks']
        self.assertEqual([c.model_dump(mode='json') for c in actual],reviewed)

    async def test_advance_requires_version_and_blocks_skip_and_duplicate(self):
        app,router=FastAPI(),APIRouter()
        app.state.storage=self.storage
        app.state.knowledge_base_service=NS(get_document=AsyncMock(return_value=self.doc),_require_edit=AsyncMock(),_bus=None)
        def admin(r):
            if r.headers.get('x-user-id')!='owner': raise HTTPException(403)
        stages.install_routes(router,app,admin,lambda r:r.headers.get('x-user-id'));app.include_router(router)
        self.doc.status=stages.WAIT_PARSE;self.doc.data.parsing_result={'version':'v1'}
        enqueue = AsyncMock()
        mocked = patch.object(stages,'enqueue_index_task',new=enqueue)
        mocked.start(); self.addCleanup(mocked.stop)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            path='/parsing/kb/documents/doc/advance';h={'x-user-id':'owner'}
            self.assertEqual((await c.post('/parsing/kb/documents/doc/draft/reset')).status_code,403)
            self.assertEqual((await c.post(path,json={'action':'chunk','version':'v1'})).status_code,403)
            self.assertEqual((await c.post(path,headers=h,json={'action':'embed','version':'v1'})).status_code,409)
            self.assertEqual((await c.post(path,headers=h,json={'action':'chunk','version':'old'})).status_code,409)
            self.assertEqual((await c.post(path,headers=h,json={'action':'chunk','version':'v1'})).status_code,200)
            self.assertEqual((await c.post(path,headers=h,json={'action':'chunk','version':'v1'})).status_code,409)
            enqueue.assert_awaited_once(); self.assertEqual(self.doc.data.stage_action,'chunk')

    async def test_custom_config_persists_in_preview_and_embeds_exactly_that_draft(self):
        from document_chunking import ChunkingConfig
        self.doc.data.parsing_result={'version':'v1','artifacts':{'document.md':{'uri':'md'}}}
        self.doc.data.confirmed_parsing_version='v1'
        self.doc.data.chunking_config=ChunkingConfig(mode='parent_child',parent_mode='full',child_max_length=50).model_dump()
        self.doc.data.stage_action='chunk'
        await stages.process_stage(self.doc,self.worker)
        self.assertEqual(self.doc.data.chunk_draft['config'],self.doc.data.chunking_config)
        self.manager.get_knowledge.assert_not_called()
        chunks=json.loads(self.files[self.doc.data.chunk_draft['uri']])
        self.assertTrue(all(c['metadata']['parent_text'] for c in chunks))
        self.doc.data.stage_action='embed';self.doc.data.confirmed_chunks_version=self.doc.data.chunk_draft['version']
        await stages.process_stage(self.doc,self.worker)
        self.assertEqual([c.model_dump(mode='json') for c in self.knowledge.insert_document.call_args.kwargs['chunks']],chunks)

    async def test_embed_rejects_settings_changed_since_preview(self):
        from document_chunking import ChunkingConfig
        app,router=FastAPI(),APIRouter(); app.state.storage=self.storage
        app.state.knowledge_base_service=NS(get_document=AsyncMock(return_value=self.doc),_require_edit=AsyncMock(),_bus=None)
        stages.install_routes(router,app,lambda r:None,lambda r:'owner');app.include_router(router)
        self.doc.status=stages.WAIT_CHUNKS
        self.doc.data.parsing_result={'version':'p1'};self.doc.data.confirmed_parsing_version='p1'
        original=ChunkingConfig().model_dump()
        self.doc.data.chunk_draft={'version':'d1','parsing_version':'p1','config':original}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            path='/parsing/kb/documents/doc/advance'
            with patch.object(stages,'enqueue_index_task',new=AsyncMock()) as enqueue:
                changed={**original,'max_length':512}
                self.assertEqual((await c.post(path,json={'action':'embed','version':'d1','config':changed})).status_code,409)
                self.assertEqual((await c.post(path,json={'action':'chunk','version':'p1','config':{**original,'overlap':1024}})).status_code,422)
                enqueue.assert_not_awaited()
                response=await c.post(path,json={'action':'embed','version':'d1','config':original})
                self.assertEqual(response.status_code,200);enqueue.assert_awaited_once()

    async def test_notebook_edit_insert_version_guard_and_embed(self):
        from document_chunking import ChunkingConfig
        self.files['md']=b'A'*300
        self.doc.data.parsing_result={'version':'p1','artifacts':{'document.md':{'uri':'md'}}}
        self.doc.data.confirmed_parsing_version='p1';self.doc.data.stage_action='chunk'
        self.doc.data.chunking_config=ChunkingConfig(mode='parent_child',parent_max_length=200,child_max_length=50).model_dump()
        await stages.process_stage(self.doc,self.worker)
        app,router=FastAPI(),APIRouter();app.state.storage=self.storage;app.state.blob_store=self.blobs
        app.state.knowledge_base_service=NS(get_document=AsyncMock(return_value=self.doc),_require_edit=AsyncMock(),_bus=None)
        def admin(r):
            if r.headers.get('x-user-id')!='owner': raise HTTPException(403)
        stages.install_routes(router,app,admin,lambda r:r.headers.get('x-user-id'));app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            path='/parsing/kb/documents/doc/draft';headers={'x-user-id':'owner'}
            version=self.doc.data.chunk_draft['version']
            body={'version':version,'action':'insert','chunk_index':-1,'text':'Inserted first'}
            self.assertEqual((await c.patch(path,json=body)).status_code,403)
            response=await c.patch(path,headers=headers,json=body);self.assertEqual(response.status_code,200)
            self.assertNotEqual(response.json()['version'],version)
            self.assertEqual((await c.patch(path,headers=headers,json=body)).status_code,409)
            version=response.json()['version']
            body={'version':version,'action':'edit','chunk_index':1,'text':'Edited content'}
            response=await c.patch(path,headers=headers,json=body);self.assertEqual(response.status_code,200)
            version=response.json()['version']
            rows=json.loads(self.files[self.doc.data.chunk_draft['uri']])
            for position in (2,len(rows)-1):
                response=await c.patch(path,headers=headers,json={'version':version,'action':'insert','chunk_index':position,'text':f'Inserted at {position}'})
                self.assertEqual(response.status_code,200);version=response.json()['version']
            rows=json.loads(self.files[self.doc.data.chunk_draft['uri']])
            self.assertEqual(rows[0]['content']['text'],'Inserted first')
            self.assertEqual(rows[1]['content']['text'],'Edited content')
            self.assertEqual(rows[0]['metadata']['draft_change'],'added')
            self.assertEqual(rows[1]['metadata']['draft_change'],'modified')
            self.assertIn('Edited content',rows[0]['metadata']['parent_text'])
            self.assertEqual([r['chunk_index'] for r in rows],list(range(len(rows))))
            self.assertTrue(all(r['total_chunks']==len(rows) for r in rows))
            delete_body={'version':version,'action':'delete','chunk_index':1}
            self.assertEqual((await c.patch(path,json=delete_body)).status_code,403)
            response=await c.patch(path,headers=headers,json=delete_body)
            self.assertEqual(response.status_code,200)
            self.assertEqual((await c.patch(path,headers=headers,json=delete_body)).status_code,409)
            version=response.json()['version']
            deleted_rows=json.loads(self.files[self.doc.data.chunk_draft['uri']])
            self.assertEqual(len(deleted_rows),len(rows))
            self.assertEqual(deleted_rows[1]['metadata']['draft_change'],'deleted')
            self.assertEqual(deleted_rows[1]['content']['text'],'Edited content')
            self.assertNotIn('Edited content',deleted_rows[0]['metadata']['parent_text'])
            self.assertEqual([r['chunk_index'] for r in deleted_rows],list(range(len(deleted_rows))))
            self.assertTrue(all(r['total_chunks']==len(deleted_rows) for r in deleted_rows))
            for position in (-1,len(deleted_rows)):
                self.assertEqual((await c.patch(path,headers=headers,json={'version':version,'action':'delete','chunk_index':position})).status_code,409)
            with self.assertRaises(HTTPException) as last:
                stages.edit_chunks(deleted_rows[:1],stages.DraftEdit(version=version,action='delete',chunk_index=0))
            self.assertEqual(last.exception.status_code,422)
            self.assertEqual((await c.patch(path,headers=headers,json={'version':version,'action':'edit','chunk_index':1,'text':'Cannot edit deleted'})).status_code,409)
            rows=[r for r in deleted_rows if r['metadata'].get('draft_change') != 'deleted']
            for i,row in enumerate(rows):
                row['chunk_index']=i;row['total_chunks']=len(rows)
            self.manager.get_knowledge.assert_not_called()
            self.doc.data.stage_action='embed';self.doc.data.confirmed_chunks_version=version
            await stages.process_stage(self.doc,self.worker)
            for row in rows: row['metadata'].pop('draft_change',None)
            self.assertEqual([ch.model_dump(mode='json') for ch in self.knowledge.insert_document.call_args.kwargs['chunks']],rows)
            self.assertEqual(self.doc.data.chunk_count,len(rows))
            result=await c.get(path,headers=headers)
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json()['total'],len(rows))
            self.assertTrue(all('draft_change' not in r['metadata'] for r in result.json()['chunks']))
            self.assertEqual((await c.patch(path,headers=headers,json={**body,'version':version})).status_code,409)
