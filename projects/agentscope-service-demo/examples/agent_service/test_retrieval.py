"""No live model calls and no writes to production data."""
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import httpx
from pydantic import ValidationError
from fastapi import APIRouter, FastAPI, HTTPException
import portal
import test_document_permissions as acl
from retrieval import RetrievalSettings, bm25, fuse, rerank, tokens, install_routes
from agentscope.app._service._document_access import AuthorizedKnowledge
from agentscope.rag._vdb import VectorSearchResult
from agentscope.rag import Chunk
from agentscope.message import TextBlock


def hit(id, text, score=1):
    return VectorSearchResult(document_id=id, score=score,
        chunk=Chunk(content=TextBlock(text=text), source=id, chunk_index=0, total_chunks=1))


class RetrievalTests(acl.PermissionTests):
    def test_bm25_chinese_and_exact_codes(self):
        rows = [hit('a', '岩亮巨眼具有发光器官'), hit('b', 'ERR_403 means forbidden'), hit('c', 'unrelated')]
        self.assertEqual(bm25(rows, '岩亮巨眼', 5)[0].document_id, 'a')
        self.assertEqual(bm25(rows, 'ERR_403', 5)[0].document_id, 'b')
        self.assertEqual(bm25(rows, 'absent', 5), [])
        self.assertIn('巨眼', tokens('巨眼'))

    def test_fusion_weight_edges_and_duplicates(self):
        a, b = hit('a', 'a'), hit('b', 'b')
        self.assertEqual([h.document_id for h in fuse([a], [b], 1, 5)], ['a'])
        self.assertEqual([h.document_id for h in fuse([a], [b], 0, 5)], ['b'])
        result = fuse([a, b], [b], .5, 5)
        self.assertEqual(result[0].document_id, 'b')
        self.assertEqual(len(result), 2)
        self.assertTrue(all(0 <= h.score <= 1 for h in result))

    def test_validation(self):
        for data in ({'top_k': 51}, {'candidate_k': 2}, {'strategy': 'bogus'},
                     {'rerank_enabled': True}, {'strategy': 'keyword', 'score_threshold': .5}):
            with self.assertRaises(ValidationError):
                RetrievalSettings(**data)

    async def test_every_strategy_filters_documents(self):
        wrapped = AuthorizedKnowledge(self.knowledge, self.access, self.storage, 'bob', portal.ADMIN, 'kb')
        for strategy in ('keyword', 'hybrid', 'vector'):
            result = await wrapped.search(['public private team'], retrieval_options={'strategy': strategy})
            self.assertEqual({r.document_id for r in result}, {'public'})
        # Keyword mode must work without calling an embedding model.
        with patch.object(self.knowledge, 'search', AsyncMock(side_effect=AssertionError('embedding called'))):
            self.assertEqual(len(await wrapped.search(['public'], retrieval_options={'strategy': 'keyword'})), 1)

    async def test_saved_default_used_in_chat_and_test_does_not_save(self):
        data = portal.load()
        data['knowledge_retrieval'] = {'kb': {'strategy': 'keyword'}}
        portal.save(data)
        wrapped = AuthorizedKnowledge(self.knowledge, self.access, self.storage, 'bob', portal.ADMIN, 'kb')
        self.assertEqual(await wrapped.search(['absent']), [])
        self.assertEqual(len(await wrapped.search(['absent'], retrieval_options={'strategy': 'vector'})), 1)
        self.assertEqual(portal.load()['knowledge_retrieval']['kb']['strategy'], 'keyword')

    async def test_revoke_before_rerank_does_not_send_document(self):
        async def revoke(*args, **kwargs):
            self.docs[0].data.access_mode = 'private'
            return [hit('public', 'sensitive content')]
        wrapped = AuthorizedKnowledge(self.knowledge, self.access, self.storage, 'bob', portal.ADMIN, 'kb')
        with (patch('retrieval.rerank_credentials', AsyncMock()), patch('retrieval.rerank', AsyncMock(return_value=[])) as rank,
              patch.object(self.knowledge, 'search', revoke)):
            await wrapped.search(['public'], retrieval_options={'rerank_enabled': True, 'credential_id': 'cred', 'model': 'r'})
            self.assertEqual(rank.await_args.args[-1], [])

    async def test_rerank_contract_and_failure(self):
        cfg = RetrievalSettings(rerank_enabled=True, credential_id='cred', model='r', top_k=1)
        requests = []
        def response(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={'results': [{'index': 1, 'relevance_score': .9}]})
        client = httpx.AsyncClient(transport=httpx.MockTransport(response))
        with (patch('retrieval.rerank_credentials', AsyncMock(return_value=({'api_key': 'fake'}, 'https://test/v1'))),
              patch('retrieval.httpx.AsyncClient', return_value=client)):
            result = await rerank(self.access, 'bob', cfg, 'q', [hit('a','first'), hit('b','second')])
        self.assertEqual(result[0].document_id, 'b')
        self.assertEqual(requests[0]['documents'], ['first', 'second'])
        self.assertEqual(requests[0]['top_n'], 1)
        bad = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'results':[{'index': 999, 'relevance_score':1}]})))
        with patch('retrieval.rerank_credentials', AsyncMock(return_value=({'api_key':'fake'}, 'https://test/v1'))), patch('retrieval.httpx.AsyncClient', return_value=bad):
            with self.assertRaises(HTTPException) as caught:
                await rerank(self.access, 'bob', cfg, 'q', [hit('a','a')])
            self.assertEqual(caught.exception.status_code, 502)

    async def test_routes_persist_default_and_protect_write(self):
        app, router = FastAPI(), APIRouter()
        app.state.storage, app.state.resource_access_service = self.storage, self.access
        app.state.knowledge_base_manager = NS(get_knowledge=AsyncMock(return_value=self.knowledge))
        self.access.list_resource = AsyncMock(return_value=[])
        def caller(r): return r.headers['x-user-id']
        def admin(r):
            if caller(r) != portal.ADMIN: raise HTTPException(403)
        install_routes(router, app, admin, caller)
        app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            user, owner = {'x-user-id':'bob'}, {'x-user-id':portal.ADMIN}
            self.assertEqual((await client.get('/retrieval/models', headers=user)).json(), {'models':[]})
            self.assertEqual((await client.patch('/retrieval/kb', headers=user, json={'strategy':'keyword'})).status_code, 403)
            self.assertEqual((await client.patch('/retrieval/kb', headers=owner, json={'strategy':'keyword'})).status_code, 200)
            self.assertEqual((await client.get('/retrieval/kb', headers=user)).json()['strategy'], 'keyword')
            response = await client.post('/retrieval/kb/test', headers=user, json={'strategy':'keyword', 'query':'public private'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual([r['document_id'] for r in response.json()['results']], ['public'])
            self.assertEqual(response.json()['score_kind'], 'BM25')
            self.assertEqual((await client.post('/retrieval/kb/test', headers=user, json={'query':' '})).status_code, 400)
