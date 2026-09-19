"""Selectable retrieval for both the workbench and live, ACL-scoped RAG.

BM25 builds a request-local inverted index from authorized Qdrant chunks. No
second persistent index (or stale ACL cache) is introduced. Large corpora fail
explicitly instead of silently searching only their first N chunks.
"""
import asyncio
import math
import re
import time
from collections import Counter, defaultdict
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from agentscope.rag._vdb import VectorSearchResult
from agentscope.app._service._document_access import AuthorizedKnowledge
from agentscope.app.access import ResourceKind


class RetrievalSettings(BaseModel):
    strategy: Literal['vector', 'keyword', 'hybrid'] = 'vector'
    top_k: int = Field(5, ge=1, le=50)
    candidate_k: int = Field(20, ge=1, le=100)
    vector_weight: float = Field(0.5, ge=0, le=1)
    score_threshold: float | None = Field(None, ge=0, le=1)
    rerank_enabled: bool = False
    credential_id: str | None = None
    model: str | None = None

    @model_validator(mode='after')
    def check(self):
        if self.candidate_k < self.top_k:
            raise ValueError('候选数不能小于 Top K')
        if self.rerank_enabled and not (self.credential_id and self.model):
            raise ValueError('请先选择已配置并启用的 Rerank 模型')
        if self.strategy == 'keyword' and not self.rerank_enabled and self.score_threshold is not None:
            raise ValueError('BM25 原始分数不适用 0–1 阈值，请关闭阈值或启用重排')
        return self


class TestRequest(RetrievalSettings):
    query: str = Field(min_length=1, max_length=4000)


def tokens(text):
    """Latin words/numbers plus Chinese characters and overlapping bigrams."""
    output = []
    for part in re.findall(r'[a-z0-9_]+|[\u3400-\u9fff]+', text.lower()):
        if '\u3400' <= part[0] <= '\u9fff':
            output.extend(part)
            output.extend(part[i:i+2] for i in range(len(part)-1))
        else:
            output.append(part)
    return output


def chunk_text(hit):
    return getattr(hit.chunk.content, 'text', '') or ''


def bm25(rows, query, limit):
    postings = defaultdict(list)
    lengths = []
    for index, row in enumerate(rows):
        terms = tokens(chunk_text(row))
        lengths.append(len(terms))
        for term, frequency in Counter(terms).items():
            postings[term].append((index, frequency))
    if not rows:
        return []
    average = sum(lengths) / len(rows) or 1
    scores = defaultdict(float)
    for term in set(tokens(query)):
        matches = postings.get(term, [])
        idf = math.log(1 + (len(rows) - len(matches) + 0.5) / (len(matches) + 0.5))
        for index, frequency in matches:
            scores[index] += idf * frequency * 2.5 / (frequency + 1.5 * (0.25 + 0.75 * lengths[index] / average))
    return [rows[index].model_copy(update={'score': score})
            for index, score in sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:limit] if score > 0]


def fuse(dense, sparse, weight, limit):
    """Weighted reciprocal rank fusion, scaled to [0, 1], not a probability."""
    hits, scores = {}, defaultdict(float)
    for rows, w in ((dense, weight), (sparse, 1 - weight)):
        if w == 0:
            continue
        for rank, row in enumerate(rows, 1):
            key = (row.document_id, row.chunk.chunk_index)
            hits[key] = row
            scores[key] += w * 61 / (60 + rank)
    return [hits[key].model_copy(update={'score': value})
            for key, value in sorted(scores.items(), key=lambda x: -x[1])[:limit]]


async def lexical_rows(knowledge, documents):
    rows = []
    for doc in documents:
        offset = 0
        while True:
            chunks = await knowledge._vector_store.list_chunks(
                knowledge._collection, doc.id, offset=offset, limit=256,
                metadata_filter=knowledge._metadata_filter)
            rows.extend(VectorSearchResult(document_id=doc.id, chunk=c, score=0) for c in chunks)
            if len(rows) > 20000:
                raise HTTPException(422, '全文检索当前支持最多 20000 个可访问分块；请缩小知识库或使用向量检索。')
            if len(chunks) < 256:
                break
            offset += 256
    return rows


async def rerank_credentials(access, viewer, settings):
    from portal import load
    record = await access.resolve_credential(viewer, settings.credential_id)
    cached = load().get('official_models', {}).get(record.id, {})
    config = cached.get('model_configs', {}).get(settings.model, {})
    if (not cached.get('selection_initialized') or settings.model not in cached.get('enabled_models', [])
            or cached.get('model_types', {}).get(settings.model) != 'rerank'
            or not config.get('context_size')):
        raise HTTPException(400, '重排模型未配置、未启用或类型不是 Rerank，请到凭证页检查。')
    data = record.model_dump()['data']
    if data.get('type') != 'openai_credential':
        raise HTTPException(400, '当前支持 OpenAI 兼容凭证的 /rerank 接口（如 SiliconFlow）。')
    base = (data.get('base_url') or '').rstrip('/')
    if urlparse(base).scheme not in ('http', 'https') or not urlparse(base).netloc:
        raise HTTPException(400, '请配置重排服务的 Base URL')
    return data, base


async def rerank(access, viewer, settings, query, hits):
    data, base = await rerank_credentials(access, viewer, settings)
    if not hits:
        return []
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.post(base + '/rerank',
                headers={'Authorization': 'Bearer ' + data.get('api_key', '')},
                json={'model': settings.model, 'query': query,
                      'documents': [chunk_text(h) for h in hits], 'top_n': settings.top_k,
                      'return_documents': False})
        if not response.is_success:
            raise HTTPException(502, f'重排服务返回 HTTP {response.status_code}；请检查模型、端点、额度和输入长度。')
        payload = response.json()
        results, seen = [], set()
        for row in payload['results']:
            index, score = row['index'], float(row['relevance_score'])
            if type(index) is not int or index < 0 or index >= len(hits) or index in seen or not math.isfinite(score):
                raise ValueError('invalid rerank result')
            seen.add(index)
            results.append(hits[index].model_copy(update={'score': score}))
        return sorted(results, key=lambda h: -h.score)[:settings.top_k]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(502, '重排服务不可达或响应格式不兼容；未降级为未重排结果。') from None


async def retrieve(knowledge, documents, queries, settings, access, viewer, filter_hits=None):
    if settings.rerank_enabled:
        await rerank_credentials(access, viewer, settings)
    corpus = await lexical_rows(knowledge, documents) if settings.strategy != 'vector' else []
    merged = {}
    for query in queries:
        dense = await knowledge.search([query], top_k=settings.candidate_k) if settings.strategy != 'keyword' else []
        sparse = await asyncio.to_thread(bm25, corpus, query, settings.candidate_k) if settings.strategy != 'vector' else []
        hits = (dense if settings.strategy == 'vector' else sparse if settings.strategy == 'keyword'
                else fuse(dense, sparse, settings.vector_weight, settings.candidate_k))
        if settings.rerank_enabled:
            if filter_hits:
                hits = await filter_hits(hits)
            hits = await rerank(access, viewer, settings, query, hits)
        for hit in hits:
            if settings.score_threshold is not None and hit.score < settings.score_threshold:
                continue
            key = (hit.document_id, hit.chunk.chunk_index)
            if key not in merged or hit.score > merged[key].score:
                merged[key] = hit
    from document_chunking import expand_parent_hits
    return expand_parent_hits(sorted(merged.values(), key=lambda h: -h.score))[:settings.top_k]


def install_routes(router, app, require_admin, caller):
    from portal import load, save, LOCK

    @router.get('/retrieval/models')
    async def models(request: Request):
        records = await app.state.resource_access_service.list_resource(caller(request), ResourceKind.CREDENTIAL)
        catalog, output = load().get('official_models', {}), []
        for record in records:
            cached = catalog.get(record.id, {})
            if record.data.get('type') != 'openai_credential' or not cached.get('selection_initialized'):
                continue
            for name in cached.get('enabled_models', []):
                if cached.get('model_types', {}).get(name) == 'rerank' and cached.get('model_configs', {}).get(name, {}).get('context_size'):
                    output.append({'credential_id': record.id, 'credential_name': record.data.get('name', record.id), 'model': name})
        return {'models': output}

    @router.get('/retrieval/{kb_id}')
    async def settings(kb_id: str, request: Request):
        await app.state.resource_access_service.resolve_knowledge_base(caller(request), kb_id)
        return RetrievalSettings.model_validate(load().get('knowledge_retrieval', {}).get(kb_id, {}))

    @router.patch('/retrieval/{kb_id}')
    async def update(kb_id: str, body: RetrievalSettings, request: Request):
        require_admin(request)
        await app.state.resource_access_service.resolve_knowledge_base(caller(request), kb_id)
        if body.rerank_enabled:
            await rerank_credentials(app.state.resource_access_service, caller(request), body)
        with LOCK:
            data = load()
            data.setdefault('knowledge_retrieval', {})[kb_id] = body.model_dump()
            save(data)
        return body

    @router.post('/retrieval/{kb_id}/test')
    async def test(kb_id: str, body: TestRequest, request: Request):
        if not body.query.strip():
            raise HTTPException(400, '请输入测试问题')
        start = time.perf_counter()
        access = app.state.resource_access_service
        kb = await access.resolve_knowledge_base(caller(request), kb_id)
        knowledge = await app.state.knowledge_base_manager.get_knowledge(kb.user_id, kb_id)
        authorized = AuthorizedKnowledge(knowledge, access, app.state.storage, caller(request), kb.user_id, kb_id)
        settings = RetrievalSettings.model_validate(body.model_dump())
        hits = await authorized.search([body.query.strip()], retrieval_options=settings.model_dump())
        score_kind = 'Rerank' if settings.rerank_enabled else {'vector': '向量相似度', 'keyword': 'BM25', 'hybrid': '加权 RRF'}[settings.strategy]
        return {'results': hits, 'total': len(hits), 'elapsed_ms': round((time.perf_counter() - start) * 1000),
                'score_kind': score_kind, 'settings': settings, 'query': body.query.strip()}
