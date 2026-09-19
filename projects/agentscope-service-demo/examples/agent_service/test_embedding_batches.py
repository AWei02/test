import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from agentscope.embedding._openai._model import OpenAIEmbeddingModel

class BatchTests(unittest.IsolatedAsyncioTestCase):
    def model(self, create):
        m = object.__new__(OpenAIEmbeddingModel)
        m.model='test'; m.dimensions=2; m.pass_dimensions=True; m.embedding_cache=None
        m._request_semaphore=asyncio.Semaphore(4)
        m.client=NS(embeddings=NS(create=AsyncMock(side_effect=create)))
        return m

    async def test_repeated_indices_reissued_without_misalignment(self):
        async def create(**kw):
            values=kw['input']
            return NS(data=[NS(index=i%8,embedding=[float(x),1.]) for i,x in enumerate(values)],usage=NS(total_tokens=len(values)))
        m=self.model(create)
        response=await m._call_api([str(i) for i in range(32)])
        self.assertEqual(response.embeddings,[[float(i),1.] for i in range(32)])
        self.assertEqual(m.client.embeddings.create.call_count,7)

    async def test_valid_out_of_order_indices_preserved(self):
        async def create(**kw):
            return NS(data=[NS(index=1,embedding=[2.,1.]),NS(index=0,embedding=[1.,1.])],usage=NS(total_tokens=2))
        response=await self.model(create)._call_api(['one','two'])
        self.assertEqual(response.embeddings,[[1.,1.],[2.,1.]])

    async def test_null_wrong_dimension_and_nan_never_cached(self):
        for vector in (None,[1.],[float('nan'),1.]):
            async def create(**kw): return NS(data=[NS(index=0,embedding=vector)],usage=NS(total_tokens=1))
            m=self.model(create); m.embedding_cache=NS(retrieve=AsyncMock(return_value=[None]),store=AsyncMock())
            with self.assertRaises(RuntimeError): await m._call_api(['one'])
            m.embedding_cache.store.assert_not_called()

    async def test_missing_response_split_to_single_inputs(self):
        async def create(**kw): return NS(data=[NS(index=0,embedding=[float(kw['input'][0]),1.])],usage=NS(total_tokens=1))
        response=await self.model(create)._call_api(['1','2','3'])
        self.assertEqual(response.embeddings,[[1.,1.],[2.,1.],[3.,1.]])
