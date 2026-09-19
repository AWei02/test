"""Audit integration tests: real Agent tracing, isolated DB and mocked model."""
import asyncio
import csv
import io
import time
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI, APIRouter
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
import portal
from project_files import member_key
from execution_audit import AuditStore, AuditObserver, AuditMiddleware, LocalSpanProcessor, install_routes, clean

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
from utils import MockModel
from tracing_test import WeatherTool, HitlWeatherTool, _make_tool_call_response, _make_text_response
from agentscope.event import RequireUserConfirmEvent, UserConfirmResultEvent, ConfirmResult, HintBlockEvent
from agentscope.agent import Agent
from agentscope.tool import Toolkit
from agentscope.message import UserMsg
from agentscope.app._service._chat import ChatService


class AuditTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        provider = TracerProvider()
        provider.add_span_processor(LocalSpanProcessor())
        trace.set_tracer_provider(provider)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(portal, 'FILE', Path(self.tmp.name) / 'portal.json')
        self.patch.start()
        data = portal.load()
        data['users'] += [{'username': u, 'enabled': True, 'role': '普通用户'} for u in ('alice', 'bob')]
        data['projects'] = {'p': {'id': 'p', 'name': 'Project', 'owner': portal.ADMIN, 'shared': True, 'agent_id': 'a'}}
        data['grants'] = [{'agent_id': 'a', 'subject_type': 'user', 'subject': u, **{k: [] for k in portal.FIELDS}} for u in ('alice', 'bob')]
        data['project_sessions'] = {member_key(u, 'a', u): 'p' for u in ('alice', 'bob')}
        portal.save(data)
        self.store = AuditStore(Path(self.tmp.name) / 'audit.sqlite3')
        self.storage = NS(get_session=AsyncMock(return_value=NS(config=NS(name='Test'), origin=NS(type='user'))))
        self.observer = AuditObserver(self.store, self.storage)

    def tearDown(self):
        self.patch.stop(); self.tmp.cleanup()

    async def run_agent(self, user, stream=False):
        model = MockModel()
        responses = [_make_tool_call_response('call-'+user, user), _make_text_response('answer-'+user)]
        model.set_responses([[r] for r in responses] if stream else responses)
        agent = Agent(name='test', system_prompt='Test', model=model, toolkit=Toolkit(tools=[WeatherTool()]), middlewares=[AuditMiddleware()])
        agent.state.session_id = user
        msg = UserMsg(name=user, content='question-'+user)
        async with self.observer.run(user, user, 'a', msg):
            reply = await agent.reply(msg)
        rows, _ = self.store.query({'user_id': user})
        return rows[0], reply

    async def test_real_agent_streaming_concurrency_and_token_totals(self):
        results = await asyncio.gather(self.run_agent('alice', True), self.run_agent('bob'))
        for (row, reply), user in zip(results, ('alice', 'bob')):
            self.assertEqual(row['status'], 'completed')
            self.assertEqual(row['input'], 'question-'+user)
            self.assertIn('answer-'+user, row['output'])
            self.assertIn(reply.id, row['reply_ids'])
            self.assertEqual(row['tool_count'], 1)
            self.assertGreater(row['input_tokens'], 0)
            self.assertEqual(row['project_id'], 'p')
            self.assertNotIn('answer-'+('bob' if user == 'alice' else 'alice'), str(row))
            model_spans = [s for s in row['spans'] if s['attributes'].get('gen_ai.operation.name') == 'chat']
            self.assertEqual(len(model_spans), 2)
            self.assertEqual(row['input_tokens'], sum(s['attributes']['gen_ai.usage.input_tokens'] for s in model_spans))

    async def test_service_failure_and_cancellation(self):
        service = object.__new__(ChatService)
        service.audit_observer = self.observer
        service._run_impl = AsyncMock(side_effect=ValueError('setup failed'))
        await service.run('alice', 'alice', 'a', UserMsg(name='alice', content='fail'))
        rows, _ = self.store.query({'user_id': 'alice'})
        self.assertEqual(rows[0]['status'], 'error')
        self.assertIn('setup failed', rows[0]['error'])
        service._run_impl = AsyncMock(side_effect=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await service.run('bob', 'bob', 'a')
        rows, _ = self.store.query({'user_id': 'bob'})
        self.assertEqual(rows[0]['status'], 'cancelled')

    async def test_storage_failure_does_not_break_chat(self):
        with patch.object(self.store, 'save', side_effect=OSError('disk unavailable')):
            async with self.observer.run('alice', 'alice', 'a', None):
                pass

    async def test_model_error_and_hint_source(self):
        model = MockModel(); model.set_responses([ValueError('model failed')])
        agent = Agent(name='test', system_prompt='test', model=model, middlewares=[AuditMiddleware()])
        with self.assertRaisesRegex(ValueError, 'model failed'):
            async with self.observer.run('alice', 'alice', 'a', None):
                await agent.reply(UserMsg(name='alice', content='test'))
        rows, _ = self.store.query({'user_id': 'alice'})
        self.assertEqual(rows[0]['status'], 'error')
        self.assertTrue(any(s['status'] == 'ERROR' for s in rows[0]['spans']))
        row = {'reply_ids': [], 'triggers': [], 'input': '', 'source': 'background'}
        AuditMiddleware.capture(row, HintBlockEvent(reply_id='r', block_id='b', source='{"label":"schedule","sublabel":"daily"}', hint='scheduled question'))
        self.assertEqual(row['source'], 'schedule')
        self.assertEqual(row['input'], 'scheduled question')

    async def test_human_confirmation_continuation(self):
        model = MockModel(); model.set_responses([_make_tool_call_response('h', 'Shanghai')])
        agent = Agent(name='hitl', system_prompt='test', model=model, toolkit=Toolkit(tools=[HitlWeatherTool()]), middlewares=[AuditMiddleware()])
        request = UserMsg(name='alice', content='weather')
        pending = None
        async with self.observer.run('alice', 'alice', 'a', request):
            async for event in agent.reply_stream(request):
                if isinstance(event, RequireUserConfirmEvent): pending = event
        self.assertIsNotNone(pending)
        rows, _ = self.store.query({'user_id': 'alice'})
        self.assertEqual(rows[0]['status'], 'waiting')
        model.set_responses([_make_text_response('sunny')])
        confirm = UserConfirmResultEvent(reply_id=pending.reply_id, confirm_results=[ConfirmResult(confirmed=True, tool_call=pending.tool_calls[0])])
        async with self.observer.run('alice', 'alice', 'a', confirm):
            await agent.reply(inputs=confirm)
        rows, _ = self.store.query({'user_id': 'alice'})
        self.assertEqual(rows[0]['status'], 'completed')
        self.assertTrue(all(pending.reply_id in r['reply_ids'] for r in rows))

    async def test_permissions_pagination_and_reply_lookup(self):
        alice, reply = await self.run_agent('alice')
        bob, _ = await self.run_agent('bob')
        app = FastAPI(); app.state.storage = self.storage; app.state.audit_observer = self.observer
        router = APIRouter(prefix='/portal'); install_routes(router, app); app.include_router(router)
        with TestClient(app) as client:
            def get(path, user='alice'):
                return client.get('/portal'+path, headers={'x-user-id': user})
            self.assertEqual([r['id'] for r in get('/projects/p/audit').json()['items']], [alice['id']])
            self.assertEqual(get('/audit/runs/'+bob['id']).status_code, 404)
            self.assertEqual(get('/audit/runs/'+bob['id'], portal.ADMIN).status_code, 200)
            page = get('/projects/p/audit?limit=1', portal.ADMIN).json()
            self.assertTrue(page['has_more'])
            page2 = get('/projects/p/audit?before='+str(page['next_before']), portal.ADMIN).json()
            self.assertEqual(len(page2['items']), 1)
            self.assertEqual(get(f'/audit/sessions/a/alice/replies/{reply.id}').json()['items'][0]['id'], alice['id'])
            self.assertEqual(get(f'/audit/sessions/a/alice/replies/{reply.id}', 'bob').json()['items'], [])
            data = portal.load(); data['grants'] = []; portal.save(data)
            self.assertEqual(get('/projects/p/audit').status_code, 404)
            self.assertEqual(get('/audit/runs/'+alice['id']).status_code, 404)

    async def test_global_audit_admin_filters_and_retained_details(self):
        alice, _ = await self.run_agent('alice')
        bob, _ = await self.run_agent('bob')
        ordinary = dict(bob, id='ordinary', project_id=None)
        self.store.save(ordinary)
        app = FastAPI(); app.state.storage = self.storage; app.state.audit_observer = self.observer
        router = APIRouter(prefix='/portal'); install_routes(router, app); app.include_router(router)
        with TestClient(app) as client:
            def get(path, user=portal.ADMIN):
                return client.get('/portal'+path, headers={'x-user-id': user})
            for path in ('/audit/runs', '/audit/options'):
                self.assertEqual(get(path, 'alice').status_code, 403)
            self.assertEqual(len(get('/audit/runs').json()['items']), 3)
            self.assertEqual(len(get('/audit/runs?user_id=bob').json()['items']), 2)
            self.assertEqual(len(get('/audit/runs?project_id=p').json()['items']), 2)
            self.assertEqual([r['id'] for r in get('/audit/runs?project_id=__ordinary__').json()['items']], ['ordinary'])
            self.assertEqual(get('/audit/runs?status=error').json()['items'], [])
            self.assertEqual(get('/audit/runs?source=channel').json()['items'], [])
            self.assertEqual(get('/audit/runs?days=31').status_code, 422)
            self.assertEqual(get('/audit/options').json()['users'], ['alice', 'bob'])
            data = portal.load(); data['projects']['p']['deleted'] = True; portal.save(data)
            self.assertEqual(get('/audit/runs/'+alice['id']).status_code, 200)
            self.assertEqual(get('/audit/runs/'+alice['id'], 'alice').status_code, 404)
            self.storage.get_session.return_value = None
            self.assertEqual(get('/audit/runs/ordinary').status_code, 200)

    def csv_client(self):
        app = FastAPI(); app.state.storage = self.storage; app.state.audit_observer = self.observer
        router = APIRouter(prefix='/portal'); install_routes(router, app); app.include_router(router)
        return TestClient(app)

    async def test_csv_complete_session_pagination_plaintext_and_permissions(self):
        long_answer = '完整回答，含逗号"和换行\n' + '长' * 25000
        older = [{'id': 'u-old', 'role': 'user', 'content': [{'type':'text','text':'=SUM(1,2)'}], 'created_at':'2025-01-01T00:00:00Z'},
                 {'id':'a-old','role':'assistant','content':[{'type':'thinking','text':'PRIVATE_THOUGHT'},{'type':'text','text':long_answer}], 'created_at':'2025-01-01T00:01:00Z'}]
        newer = [{'id':'u-new','role':'user','content':[{'type':'text','text':'新问题'}]},
                 {'id':'a-new','role':'assistant','content':[{'type':'text','text':'新回答'},{'type':'tool_call','arguments':{'secret':'PRIVATE_TOOL'}}]}]
        self.storage.list_messages = AsyncMock(side_effect=[(newer, True), (older, False)])
        with self.csv_client() as client:
            r = client.get('/portal/audit/sessions/a/alice/export.csv',headers={'x-user-id':'alice'})
            self.assertEqual(r.status_code,200)
            self.assertTrue(r.content.startswith(b'\xef\xbb\xbf'))
            rows = list(csv.DictReader(io.StringIO(r.content.decode('utf-8-sig'))))
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[0]['AI 回答'],long_answer)
            self.assertEqual(rows[0]['用户问题'],"'=SUM(1,2)")
            self.assertEqual(rows[0]['执行时间'],'2025-01-01 08:00:00')
            self.assertEqual(rows[1]['AI 回答'],'新回答')
            self.assertNotIn('PRIVATE_',r.text)
            self.assertEqual(rows[0]['来源'],'Web 对话')
            self.storage.get_session.return_value = None
            self.assertEqual(client.get('/portal/audit/sessions/a/alice/export.csv',headers={'x-user-id':'bob'}).status_code,404)

    async def test_csv_global_full_filtered_range_and_deduplication(self):
        base, _ = await self.run_agent('alice')
        messages = []
        for i in range(45):
            rid = 'csv-reply-'+str(i)
            self.store.save(dict(base,id='csv-run-'+str(i),reply_ids=[rid],input='question-'+str(i),started=time.time()-i))
            messages += [{'id':'q'+str(i),'role':'user','content':[{'type':'text','text':'question-'+str(i)}]},
                         {'id':rid,'role':'assistant','content':[{'type':'text','text':'answer-'+str(i)}]}]
        self.store.save(dict(base,id='csv-too-old',reply_ids=['old'],started=time.time()-2*86400))
        self.store.save(dict(base,id='csv-continuation',input='',reply_ids=['csv-reply-0']))
        self.storage.list_messages = AsyncMock(return_value=(messages,False))
        with self.csv_client() as client:
            url='/portal/audit/export.csv?days=1&user_id=alice&project_id=p&source=web&status=completed'
            self.assertEqual(client.get(url,headers={'x-user-id':'bob'}).status_code,403)
            r=client.get(url,headers={'x-user-id':portal.ADMIN})
            self.assertEqual(r.status_code,200)
            rows=list(csv.DictReader(io.StringIO(r.content.decode('utf-8-sig'))))
            self.assertEqual(len(rows),46)
            self.assertEqual(sum(row['用户问题']=='question-0' for row in rows),1)
            self.assertIn('answer-44',[row['AI 回答'] for row in rows])
            denied=client.get('/portal/audit/runs/'+base['id']+'/conversation.csv',headers={'x-user-id':'bob'})
            self.assertEqual(denied.status_code,404)
            self.assertEqual(client.get('/portal/audit/export.csv?days=31',headers={'x-user-id':portal.ADMIN}).status_code,422)

    def test_redaction_and_limits(self):
        value = clean({'api_key': 'private', 'nested': '{"password":"private"}', 'text': 'Bearer private'})
        self.assertNotIn('private', str(value))
        self.assertIn('截断', clean('a'*30000))


if __name__ == '__main__':
    unittest.main()
