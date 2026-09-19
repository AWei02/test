import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import FastAPI, APIRouter, HTTPException
from pydantic import ValidationError
import portal
from graph_rules import GraphRules, EntityRule, RelationRule, validate_extraction, state_for, finish_build, install_routes, BUILD_LOCKS
from graph_rag import GraphExtraction, GraphEntity, GraphRelation, GraphRagStore


def rules(mode='guided'):
    return GraphRules(mode=mode, entities=[EntityRule(name='生物', aliases=['物种']),EntityRule(name='地点')],
        relations=[RelationRule(name='栖息于',aliases=['居住于'],source_types=['生物'],target_types=['地点'])])


class RulesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(portal, 'FILE', Path(self.temp.name)/'portal.json')
        self.patch.start()
        self.graph = GraphExtraction(entities=[GraphEntity(name='狼',type='物种'),GraphEntity(name='山谷',type='地点'),GraphEntity(name='夜视',type='能力')],
            relations=[GraphRelation(source='狼', target='山谷', relation='居住于'),
                GraphRelation(source='狼',target='夜视',relation='拥有'),GraphRelation(source='山谷',target='狼',relation='栖息于'),
                GraphRelation(source='不存在',target='狼',relation='栖息于')])

    async def asyncTearDown(self):
        self.patch.stop(); self.temp.cleanup(); BUILD_LOCKS.clear()

    def test_guided_quarantines_unknown_and_validates_direction(self):
        graph, pending, rejected = validate_extraction(self.graph, rules())
        self.assertEqual([(r.source,r.relation,r.target) for r in graph.relations], [('狼','栖息于','山谷')])
        self.assertEqual({p['name'] for p in pending}, {'能力','拥有'})
        self.assertEqual(graph.entities[0].type,'生物')
        self.assertEqual(rejected,4)

    def test_strict_no_pending_free_preserves_unknown(self):
        graph,pending,_ = validate_extraction(self.graph,rules('strict'))
        self.assertEqual(len(graph.relations),1); self.assertFalse(pending)
        graph,pending,_ = validate_extraction(self.graph,rules('free'))
        self.assertEqual(len(graph.relations),3); self.assertFalse(pending)
        self.assertEqual(len(graph.entities),3)

    def test_invalid_schema_and_aliases(self):
        for value in ({'mode':'strict'}, {'mode':'nonsense'},
            {'mode':'free','entities':[{'name':'A','aliases':['a']}]},
            {'mode':'free','entities':[{'name':'A'}],'relations':[{'name':'r','source_types':['A'],'target_types':['missing']}]}):
            with self.assertRaises(ValidationError): GraphRules.model_validate(value)

    async def test_persistence_revisions_and_access(self):
        app,router = FastAPI(),APIRouter()
        app.state.resource_access_service = NS(resolve_knowledge_base=AsyncMock())
        def admin(r):
            if r.headers.get('x-user-id') != portal.ADMIN: raise HTTPException(403)
        install_routes(router,app,admin);app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            path='/knowledge-graph/kb/rules'
            self.assertEqual((await c.get(path)).status_code,403)
            h={'x-user-id':portal.ADMIN}
            self.assertEqual((await c.get(path,headers=h)).json()['revision'],0)
            result=await c.patch(path,headers=h,json=rules().model_dump())
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['revision'],1)
            self.assertIsNone(result.json()['built_revision'])
            self.assertEqual((await c.patch(path,headers=h,json=rules().model_dump())).json()['revision'],1)
            finish_build('kb',1,[{'name':'能力'}],{'relations':1})
            self.assertEqual(state_for('kb')['built_revision'],1)
            changed=rules('strict')
            self.assertEqual((await c.patch(path,headers=h,json=changed.model_dump())).json()['revision'],2)
            self.assertEqual(state_for('kb')['built_revision'],1)
            lock=BUILD_LOCKS['kb'];await lock.acquire()
            self.assertEqual((await c.patch(path,headers=h,json=changed.model_dump())).status_code,409)
            lock.release()

    async def test_replace_uses_one_transaction(self):
        tx=NS(run=AsyncMock())
        async def execute(fn): return await fn(tx)
        session=NS(execute_write=AsyncMock(side_effect=execute))
        class Context:
            async def __aenter__(self): return session
            async def __aexit__(self,*a): return False
        driver=NS(session=lambda **kw:Context(),close=AsyncMock())
        store=GraphRagStore('fake','fake','fake','fake')
        graph,_,_=validate_extraction(self.graph,rules())
        with patch.object(store,'_driver',return_value=driver):
            await store.replace_knowledge('kb',[('doc','doc.txt',0,graph)])
        session.execute_write.assert_awaited_once()
        self.assertIn('DETACH DELETE',tx.run.await_args_list[0].args[0])
        self.assertEqual(tx.run.await_args_list[-1].kwargs['document_id'],'doc')

    async def test_build_failure_keeps_old_graph_and_success_tracks_revision(self):
        app=FastAPI()
        store=NS(ensure_ready=AsyncMock(),replace_knowledge=AsyncMock(),snapshot=AsyncMock(return_value={'nodes':[],'edges':[]}))
        app.state.graph_rag_store=store
        app.state.resource_access_service=NS(resolve_knowledge_base=AsyncMock(return_value=NS(user_id=portal.ADMIN)))
        app.state.storage=NS(list_knowledge_documents=AsyncMock(return_value=[NS(id='doc',status='ready',data=NS(filename='test.txt',chunk_count=1))]))
        app.state.knowledge_base_manager=NS(get_knowledge=AsyncMock(return_value=NS(list_chunks=AsyncMock(return_value=[NS(content={'text':'狼栖息于山谷'},chunk_index=0)]))))
        portal.install_portal(app)
        data=portal.load();data['graph_rules']={'kb':{'revision':1,'rules':rules().model_dump()}};portal.save(data)
        body={'rules_revision':1,'chat_model_config':{'type':'openai','credential_id':'fake','model':'fake','parameters':{}}}
        with patch('agentscope.app._service._model.get_model',AsyncMock()):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'x-user-id':portal.ADMIN}) as c:
                with patch('graph_rag.extract_chunk_graph',AsyncMock(side_effect=RuntimeError('test failure'))):
                    result=await c.post('/portal/knowledge-graph/kb/build',json=body)
                    self.assertEqual(result.status_code,500,result.text)
                    store.replace_knowledge.assert_not_awaited()
                    self.assertFalse(BUILD_LOCKS['kb'].locked())
                with patch('graph_rag.extract_chunk_graph',AsyncMock(return_value=self.graph)):
                    result=await c.post('/portal/knowledge-graph/kb/build',json=body)
                    self.assertEqual(result.status_code,200,result.text)
                    store.replace_knowledge.assert_awaited_once()
                    self.assertEqual(state_for('kb')['built_revision'],1)
                    self.assertEqual(len(state_for('kb')['pending']),2)
                result=await c.post('/portal/knowledge-graph/kb/build',json={**body,'rules_revision':0})
                self.assertEqual(result.status_code,409)
