"""Isolated ACL regression tests; no production records or model calls."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import portal
from agentscope.app._service._document_access import AuthorizedKnowledge
from agentscope.app._service._knowledge_base import KnowledgeBaseService
from agentscope.app.storage import KnowledgeDocumentRecord, KnowledgeDocumentData
from agentscope.rag import KnowledgeBase, QdrantStore, Chunk, VectorRecord
from agentscope.message import TextBlock
from fastapi import HTTPException

class FakeEmbedding:
    supports_multimodal = False
    dimensions = 2
    async def __call__(self, queries):
        return NS(embeddings=[[1., 0.] for _ in queries])

class PermissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(portal, 'FILE', Path(self.temp.name) / 'portal.json')
        self.patch.start()
        data = portal.load()
        data['users'].extend([{'username': 'alice', 'role': 'reader', 'enabled': True},
                              {'username': 'bob', 'role': 'other', 'enabled': True}])
        data['roles'].extend(['reader', 'other'])
        portal.save(data)
        self.docs = [KnowledgeDocumentRecord(id=id, user_id=portal.ADMIN, knowledge_base_id='kb',
            data=KnowledgeDocumentData(filename=id+'.txt', size=1, blob_uri='s3://test/'+id,
                                       access_mode=mode, access_roles=roles))
            for id, mode, roles in [('public', 'inherit', []), ('private', 'private', []), ('team', 'custom', ['reader'])]]
        self.storage = NS(list_knowledge_documents=AsyncMock(side_effect=lambda *a: self.docs),
                          get_knowledge_document=AsyncMock(side_effect=lambda u,k,d: next((r for r in self.docs if r.id == d), None)))
        self.access = NS(_policy=portal.PortalPolicy(), resolve_knowledge_base=AsyncMock(return_value=NS(user_id=portal.ADMIN)))
        self.store = QdrantStore(location=':memory:')
        await self.store.create_collection('kb', dimensions=2)
        await self.store.insert('kb', [VectorRecord(document_id=d.id, vector=[1., 0.],
            chunk=Chunk(content=TextBlock(text=d.id), source=d.data.filename, chunk_index=0, total_chunks=1)) for d in self.docs])
        self.knowledge = KnowledgeBase('test', 'test', FakeEmbedding(), self.store, 'kb')

    async def asyncTearDown(self):
        await self.store.__aexit__(None, None, None)
        self.patch.stop()
        self.temp.cleanup()

    async def test_qdrant_prefilter_and_live_revocation(self):
        a = AuthorizedKnowledge(self.knowledge, self.access, self.storage, 'alice', portal.ADMIN, 'kb')
        b = AuthorizedKnowledge(self.knowledge, self.access, self.storage, 'bob', portal.ADMIN, 'kb')
        self.assertEqual({r.document_id for r in await a.search(['x'])}, {'public', 'team'})
        self.assertEqual({r.document_id for r in await b.search(['x'])}, {'public'})
        self.docs[2].data.access_mode = 'private'
        self.assertEqual({r.document_id for r in await a.search(['x'])}, {'public'})
        self.assertIsNone(self.knowledge.metadata_filter)
        self.docs[0].data.access_mode = 'private'
        self.assertEqual(await a.search(['x']), [])

    async def test_download_and_chunks_use_same_guard(self):
        service = object.__new__(KnowledgeBaseService)
        service._storage, service._access = self.storage, self.access
        with self.assertRaises(HTTPException) as caught:
            await service.get_document('bob', 'kb', 'team')
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual((await service.get_document('alice', 'kb', 'team')).id, 'team')

    async def test_disabled_identity_denied(self):
        data = portal.load()
        next(u for u in data['users'] if u['username'] == 'alice')['enabled'] = False
        portal.save(data)
        with self.assertRaises(HTTPException):
            portal.PortalPolicy().can_read_document('alice', self.docs[0])

    async def test_legacy_records_inherit(self):
        legacy = KnowledgeDocumentData(filename='old', size=1, blob_uri='s3://test/old')
        self.assertEqual(legacy.access_mode, 'inherit')

    async def test_permission_api_persists_and_rejects_invalid_changes(self):
        from fastapi import FastAPI, APIRouter
        from httpx import AsyncClient, ASGITransport
        from document_permissions import install_routes
        app = FastAPI()
        app.state.storage = self.storage
        self.storage.upsert_knowledge_document = AsyncMock()
        app.state.resource_access_service = self.access
        router = APIRouter(prefix='/portal')
        def admin(request):
            if request.headers.get('x-user-id') != portal.ADMIN:
                raise HTTPException(403)
        install_routes(router, app, admin)
        app.include_router(router)
        self.docs[0].status = 'ready'
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            url = '/portal/document-permissions/kb/public'
            response = await client.patch(url, headers={'x-user-id': 'alice'}, json={'access_mode': 'private'})
            self.assertEqual(response.status_code, 403)
            response = await client.patch(url, headers={'x-user-id': portal.ADMIN}, json={'access_mode': 'custom'})
            self.assertEqual(response.status_code, 422)
            response = await client.patch(url, headers={'x-user-id': portal.ADMIN}, json={'access_mode': 'custom', 'access_roles': ['missing']})
            self.assertEqual(response.status_code, 400)
            response = await client.patch(url, headers={'x-user-id': portal.ADMIN}, json={'access_mode': 'custom', 'access_users': ['alice']})
            self.assertEqual(response.status_code, 200, response.text)
            self.storage.upsert_knowledge_document.assert_awaited_once()
            self.assertTrue(portal.PortalPolicy().can_read_document('alice', self.docs[0]))
            self.assertFalse(portal.PortalPolicy().can_read_document('bob', self.docs[0]))
            history = (await client.get('/portal/knowledge-permissions/kb', headers={'x-user-id': portal.ADMIN})).json()['history']
            self.assertEqual(history[0]['document_id'], 'public')

    async def test_graph_receives_only_authorized_document_ids(self):
        from graph_rag import GraphSearchTool
        graph = NS(search=AsyncMock(return_value=[]))
        workspace = NS(username='bob', storage=self.storage, selected=lambda field: {'kb'})
        await GraphSearchTool(graph, ['kb'], workspace=workspace).call('topic')
        self.assertEqual(graph.search.await_args.kwargs['document_ids'], ['public'])
        workspace.selected = lambda field: set()
        await GraphSearchTool(graph, ['kb'], workspace=workspace).call('topic')
        self.assertEqual(graph.search.await_args.kwargs['document_ids'], [])

    async def test_upload_acl_is_persisted_before_indexing(self):
        from io import BytesIO
        service = object.__new__(KnowledgeBaseService)
        service._access = self.access
        service._require_edit = AsyncMock(return_value=portal.ADMIN)
        service._blob_store = NS(write_stream=AsyncMock(return_value='s3://test/upload'))
        service._storage = NS(upsert_knowledge_document=AsyncMock(side_effect=lambda u,d: d))
        service._bus = NS()
        with patch('agentscope.app._service._knowledge_base.enqueue_index_task', new=AsyncMock()):
            doc = await service.register_document(portal.ADMIN, 'kb', 'test.txt', BytesIO(b'test'), 4,
                                                  access_mode='custom', access_users=['alice'])
            self.assertEqual(doc.data.access_users, ['alice'])
            self.assertEqual(doc.data.access_mode, 'custom')
            with self.assertRaises(HTTPException):
                await service.register_document(portal.ADMIN, 'kb', 'test.txt', BytesIO(b'test'), 4,
                                                access_mode='custom', access_users=['nonexistent'])
            self.assertEqual(service._blob_store.write_stream.await_count, 1)

if __name__ == '__main__':
    unittest.main()
