"""Persisted, explicit human gates between parsing, chunking and embedding."""
import io
import json
from datetime import timedelta, datetime, timezone
from uuid import uuid4
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from typing import Literal
from agentscope.rag import Chunk
from agentscope.app._bus_ops import enqueue_index_task
from document_parsing import parse_document, markdown_sections
from document_chunking import ChunkingConfig, build_chunks
import asyncio

WAIT_PARSE = 'awaiting_parse_confirmation'
WAIT_CHUNKS = 'awaiting_chunk_confirmation'

def has_pending_draft(document):
    data = document.data
    return bool(data.stage_action == 'chunk' and data.chunk_draft.get('version')
                and data.confirmed_chunks_version is None)


async def build_review_draft(record, blobs, config):
    result = record.data.parsing_result
    async with blobs.open(result['artifacts']['document.md']['uri']) as fp:
        raw = await fp.read()
    chunks = await asyncio.to_thread(build_chunks, raw.decode('utf-8-sig'), record.data.filename, ChunkingConfig.model_validate(config))
    version = uuid4().hex
    payload = json.dumps([c.model_dump(mode='json') for c in chunks], ensure_ascii=False).encode()
    uri = await blobs.write_stream(key=f'kb/{record.knowledge_base_id}/{record.id}/drafts/{version}.json', stream=io.BytesIO(payload))
    return {'version':version, 'parsing_version':result['version'], 'uri':uri,
            'count':len(chunks), 'config':config, 'created_at':datetime.now(timezone.utc).isoformat()}

async def process_stage(record, worker):
    storage, blobs = worker._storage, worker._blob_store
    owner, kb, doc = record.user_id, record.knowledge_base_id, record.id
    action = record.data.stage_action
    async def status(value, **kwargs):
        await storage.update_knowledge_document_status(owner, kb, doc, value, **kwargs)
    async def current():
        fresh = await storage.get_knowledge_document(owner, kb, doc)
        if fresh is None or fresh.processing_node != record.processing_node:
            raise ValueError('文件已删除或任务租约已变更')
        return fresh
    async def read(uri):
        async with blobs.open(uri) as fp: return await fp.read()

    if action == 'parse':
        await status('parsing')
        raw = await worker._read_blob(record.data.blob_uri)
        await parse_document(record, raw, storage, blobs, worker._resource_access_service)
        fresh = await current()
        fresh.data.confirmed_parsing_version = None
        fresh.data.confirmed_chunks_version = None
        fresh.data.chunk_draft = {}
        await storage.upsert_knowledge_document(owner, fresh)
        await status(WAIT_PARSE, error=None)
        return

    result = record.data.parsing_result
    if not result.get('version') or record.data.confirmed_parsing_version != result['version']:
        raise ValueError('请先确认当前版本的解析结果')
    if action == 'chunk':
        await status('chunking')
        raw = await read(result['artifacts']['document.md']['uri'])
        config = record.data.chunking_config
        if config is not None:
            chunks = await asyncio.to_thread(build_chunks, raw.decode('utf-8-sig'), record.data.filename, ChunkingConfig.model_validate(config))
        else:
            # Preserve the old token-based policy for legacy API clients/drafts.
            kb_record = await worker._manager.get_knowledge_base(owner, kb)
            chunker = worker._resolve_chunker_from_record(kb_record)
            chunks = await chunker.chunk(markdown_sections(raw.decode('utf-8-sig'), record.data.filename))
        if not chunks: raise ValueError('没有可用分片，请检查 Markdown 内容')
        version = uuid4().hex
        payload = json.dumps([c.model_dump(mode='json') for c in chunks], ensure_ascii=False).encode()
        uri = await blobs.write_stream(key=f'kb/{kb}/{doc}/drafts/{version}.json', stream=io.BytesIO(payload))
        fresh = await current()
        fresh.data.chunk_draft = {'version': version, 'parsing_version': result['version'], 'uri': uri,
            'count': len(chunks), 'config': config, 'created_at': datetime.now(timezone.utc).isoformat()}
        fresh.data.confirmed_chunks_version = None
        await storage.upsert_knowledge_document(owner, fresh)
        await status(WAIT_CHUNKS, error=None)
        return

    draft = record.data.chunk_draft
    if (not draft.get('version') or record.data.confirmed_chunks_version != draft['version']
            or draft.get('parsing_version') != result['version']):
        raise ValueError('请先确认当前版本的分片')
    await status('indexing')
    # Embed precisely the draft the user reviewed; never silently re-chunk it.
    chunks = [Chunk.model_validate(c) for c in json.loads(await read(draft['uri']))]
    chunks = [c for c in chunks if c.metadata.get('draft_change') != 'deleted']
    if not chunks:
        raise ValueError('至少保留一个有效分片')
    for i, chunk in enumerate(chunks):
        chunk.chunk_index = i
        chunk.total_chunks = len(chunks)
        chunk.metadata.pop('draft_change', None)
    knowledge = await worker._manager.get_knowledge(owner, kb)
    await knowledge.delete_document(doc)
    await knowledge.insert_document(chunks=chunks, document_id=doc, document_metadata={
        'filename': record.data.filename, 'media_type': record.data.content_type, 'size_bytes': record.data.size})
    fresh = await current()
    fresh.data.indexed_chunking_config = draft.get('config')
    await storage.upsert_knowledge_document(owner, fresh)
    await status('ready', chunk_count=len(chunks), error=None)


class Advance(BaseModel):
    action: Literal['chunk','embed']
    version: str
    config: ChunkingConfig | None = None


class DraftEdit(BaseModel):
    version: str
    action: Literal['edit', 'insert', 'delete', 'restore']
    chunk_index: int = Field(ge=-1)
    text: str = Field(default='', max_length=16000)


def edit_chunks(rows, body):
    """Update the reviewed data, never re-run the splitter or embedding model."""
    from agentscope.message import TextBlock
    if body.action not in ('delete', 'restore') and not body.text.strip():
        raise HTTPException(422, '分片内容不能为空')
    index = body.chunk_index
    if not rows or index >= len(rows) or (body.action != 'insert' and index < 0):
        raise HTTPException(409, '分片位置已变化，请刷新预览')
    chunks = [Chunk.model_validate(row) for row in rows]
    if body.action not in ('insert', 'restore') and chunks[index].metadata.get('draft_change') == 'deleted':
        raise HTTPException(409, '该分片已标记删除，请重置后再操作')
    if body.action == 'restore':
        target = chunks[index]
        if target.metadata.get('draft_change') != 'deleted':
            raise HTTPException(409, '该分片未标记删除')
        previous = target.metadata.pop('draft_before_delete', None)
        if previous in ('added', 'modified'):
            target.metadata['draft_change'] = previous
        else:
            target.metadata.pop('draft_change', None)
    elif body.action == 'delete':
        if sum(c.metadata.get('draft_change') != 'deleted' for c in chunks) <= 1:
            raise HTTPException(422, '至少保留一个分片；可编辑最后一个分片的内容')
        target = chunks[index]
        if target.metadata.get('draft_change') == 'added':
            chunks.pop(index)
        else:
            target.metadata['draft_before_delete'] = target.metadata.get('draft_change')
            target.metadata['draft_change'] = 'deleted'
    elif body.action == 'edit':
        target = chunks[index]
        if target.content.text != body.text and target.metadata.get('draft_change') != 'added':
            target.metadata['draft_change'] = 'modified'
        target.content = TextBlock(text=body.text)
    else:
        if len(chunks) >= 20000:
            raise HTTPException(422, '分片最多 20000 个')
        target = chunks[max(0, index)].model_copy(deep=True)
        target.metadata['draft_change'] = 'added'
        target.content = TextBlock(text=body.text)
        chunks.insert(index + 1, target)
    target.metadata['manually_edited'] = True
    if target.metadata.get('chunk_mode') == 'parent_child':
        parent_id = target.metadata['parent_index']
        related = [c for c in chunks if c.metadata.get('parent_index') == parent_id and c.metadata.get('draft_change') != 'deleted']
        # Child edits must appear in the context ultimately returned to the LLM.
        parent_text = '\n\n'.join(c.content.text for c in related)
        if len(parent_text) > 40000:
            raise HTTPException(422, '编辑后的父块超过 40000 字符，请缩短内容')
        for child in related:
            child.metadata['parent_text'] = parent_text
    for i, chunk in enumerate(chunks):
        chunk.chunk_index = i
        chunk.total_chunks = len(chunks)
    return chunks


def install_routes(router, app, require_admin, caller):
    @router.post('/parsing/{kb_id}/documents/{doc_id}/draft/reset')
    async def reset_draft(kb_id: str, doc_id: str, request: Request):
        require_admin(request)
        service, storage, blobs = app.state.knowledge_base_service, app.state.storage, app.state.blob_store
        document = await service.get_document(caller(request), kb_id, doc_id)
        await service._require_edit(caller(request), kb_id)
        owner, node = document.user_id, 'reset-draft:' + uuid4().hex
        if not await storage.acquire_knowledge_document_lease(owner, kb_id, doc_id, node, timedelta(seconds=60)):
            raise HTTPException(409, '文件正在处理，请稍后重置')
        try:
            document = await storage.get_knowledge_document(owner, kb_id, doc_id)
            if document is None or document.status != 'ready' or document.data.chunk_count <= 0:
                raise HTTPException(409, '仅已就绪且有向量化结果的文档可重置')
            rows = []
            for page in range(1, (document.data.chunk_count + 199)//200 + 1):
                chunks, total = await service.list_document_chunks(caller(request), kb_id, doc_id, page=page, page_size=200)
                rows.extend(c.model_copy(deep=True) for c in chunks)
            rows.sort(key=lambda c: c.chunk_index)
            if len(rows) != document.data.chunk_count or [c.chunk_index for c in rows] != list(range(len(rows))):
                raise HTTPException(409, '已入库分片不完整，无法重置')
            for chunk in rows:
                chunk.metadata.pop('draft_change', None)
                chunk.metadata.pop('manually_edited', None)
            version = uuid4().hex
            uri = await blobs.write_stream(key=f'kb/{kb_id}/{doc_id}/drafts/{version}.json', stream=io.BytesIO(json.dumps([c.model_dump(mode='json') for c in rows], ensure_ascii=False).encode()))
            fresh = await storage.get_knowledge_document(owner, kb_id, doc_id)
            if fresh is None or fresh.processing_node != node:
                raise HTTPException(409, '任务租约已变化，请重试')
            settings_known = fresh.data.indexed_chunking_config is not None
            config = fresh.data.indexed_chunking_config or ChunkingConfig().model_dump()
            # Older indexes did not retain their splitter settings. Do not
            # infer those settings from a subsequently changed preview.
            fresh.data.chunking_config = config
            fresh.data.chunk_draft = {'version':version, 'uri':uri, 'count':len(rows), 'config':config,
                'parsing_version':fresh.data.parsing_result.get('version'), 'reset_from_index':True}
            fresh.data.confirmed_parsing_version = fresh.data.parsing_result.get('version')
            fresh.data.confirmed_chunks_version = None
            fresh.data.stage_action = 'chunk'
            await storage.upsert_knowledge_document(owner, fresh)
            return {'version':version, 'count':len(rows), 'config':config, 'settings_known':settings_known}
        finally:
            await storage.release_knowledge_document_lease(owner, kb_id, doc_id, node)

    @router.patch('/parsing/{kb_id}/documents/{doc_id}/draft')
    async def edit_draft(kb_id: str, doc_id: str, body: DraftEdit, request: Request):
        require_admin(request)
        service, storage, blobs = app.state.knowledge_base_service, app.state.storage, app.state.blob_store
        document = await service.get_document(caller(request), kb_id, doc_id)
        await service._require_edit(caller(request), kb_id)
        owner, node = document.user_id, 'edit-draft:' + uuid4().hex
        if not await storage.acquire_knowledge_document_lease(owner, kb_id, doc_id, node, timedelta(seconds=30)):
            raise HTTPException(409, '文件正在处理，请稍后编辑')
        try:
            document = await storage.get_knowledge_document(owner, kb_id, doc_id)
            if document is None: raise HTTPException(404, '文件不存在')
            if document.status != WAIT_CHUNKS and not (document.status == 'ready' and has_pending_draft(document)):
                raise HTTPException(409, '仅待确认分片阶段可以编辑；已入库文件请先重新生成分片')
            draft = document.data.chunk_draft
            if not draft.get('version') or body.version != draft['version']:
                raise HTTPException(409, '草稿已变化，请刷新预览后再保存')
            if draft.get('parsing_version') != document.data.parsing_result.get('version'):
                raise HTTPException(409, '解析结果已变化，请重新生成分片')
            async with blobs.open(draft['uri']) as fp:
                rows = json.loads(await fp.read())
            chunks = edit_chunks(rows, body)
            version = uuid4().hex
            payload = json.dumps([c.model_dump(mode='json') for c in chunks], ensure_ascii=False).encode()
            uri = await blobs.write_stream(key=f'kb/{kb_id}/{doc_id}/drafts/{version}.json',stream=io.BytesIO(payload))
            document.data.chunk_draft = {**draft, 'version':version, 'uri':uri, 'count':len(chunks),
                'manual_edits':draft.get('manual_edits',0)+1, 'updated_at':datetime.now(timezone.utc).isoformat()}
            document.data.confirmed_chunks_version = None
            await storage.upsert_knowledge_document(owner, document)
        finally:
            await storage.release_knowledge_document_lease(owner, kb_id, doc_id, node)
        position = body.chunk_index + (1 if body.action == 'insert' else 0)
        position = min(max(0, position), len(chunks)-1)
        return {'version':version, 'count':len(chunks), 'page':position//20+1}

    @router.post('/parsing/{kb_id}/documents/{doc_id}/advance')
    async def advance(kb_id: str, doc_id: str, body: Advance, request: Request):
        require_admin(request)
        service, storage = app.state.knowledge_base_service, app.state.storage
        document = await service.get_document(caller(request), kb_id, doc_id)
        await service._require_edit(caller(request), kb_id)
        owner = document.user_id
        node = 'confirm:' + uuid4().hex
        if not await storage.acquire_knowledge_document_lease(owner, kb_id, doc_id, node, timedelta(seconds=30)):
            raise HTTPException(409, '任务正在执行，请等待完成')
        try:
            document = await storage.get_knowledge_document(owner, kb_id, doc_id)
            if document is None: raise HTTPException(404, '文件不存在')
            allowed = (WAIT_PARSE, WAIT_CHUNKS, 'ready', 'error') if body.action == 'chunk' else (WAIT_CHUNKS, 'error', 'ready')
            if document.status not in allowed: raise HTTPException(409, '当前阶段不可执行此操作')
            if body.action == 'embed' and document.status == 'ready' and not has_pending_draft(document):
                raise HTTPException(409, '当前分片已经入库，请先生成新的分片草稿')
            data = document.data
            version = data.parsing_result.get('version') if body.action == 'chunk' else data.chunk_draft.get('version')
            if not version or version != body.version: raise HTTPException(409, '内容已变化，请刷新并重新确认')
            # An indexed document's preview is only a draft operation. Keep the
            # active index and lifecycle ready throughout; do not enqueue an
            # indexing worker that would mark it pending/chunking.
            if body.action == 'chunk' and data.chunk_count > 0 and document.status in ('ready', WAIT_CHUNKS):
                config = body.config.model_dump() if body.config else (data.chunking_config or ChunkingConfig().model_dump())
                try:
                    draft = await build_review_draft(document, app.state.blob_store, config)
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from None
                fresh = await storage.get_knowledge_document(owner, kb_id, doc_id)
                if fresh is None or fresh.processing_node != node:
                    raise HTTPException(409, '文件已删除或任务租约已变化，请刷新后重试')
                fresh.data.chunk_draft = draft
                fresh.data.chunking_config = config
                fresh.data.confirmed_parsing_version = version
                fresh.data.confirmed_chunks_version = None
                fresh.data.manual_stages = True
                fresh.data.stage_action = 'chunk'
                fresh.data.error = None
                fresh.status = 'ready'
                await storage.upsert_knowledge_document(owner, fresh)
                return {'status':'ready','stage':'chunk','draft_pending':True}
            data.manual_stages = True
            if body.action == 'chunk':
                if body.config is not None:
                    data.chunking_config = body.config.model_dump()
                data.confirmed_parsing_version = version; data.confirmed_chunks_version = None
            else:
                if body.config is not None and body.config.model_dump() != data.chunk_draft.get('config'):
                    raise HTTPException(409, '分段设置已变化，请重新预览并确认新分片')
                if data.confirmed_parsing_version != data.chunk_draft.get('parsing_version'):
                    raise HTTPException(409, '解析版本已变化，请重新生成分片')
                data.confirmed_chunks_version = version
            data.stage_action = body.action; data.error = None; document.status = 'pending'
            await storage.upsert_knowledge_document(owner, document)
        finally:
            await storage.release_knowledge_document_lease(owner, kb_id, doc_id, node)
        await enqueue_index_task(service._bus, user_id=owner, knowledge_base_id=kb_id, document_id=doc_id)
        return {'status':'pending','stage':body.action}

    @router.get('/parsing/{kb_id}/documents/{doc_id}/draft')
    async def draft(kb_id: str, doc_id: str, request: Request, page: int = 1):
        if page < 1: raise HTTPException(400, '页码无效')
        document = await app.state.knowledge_base_service.get_document(caller(request), kb_id, doc_id)
        draft = document.data.chunk_draft
        if not draft: return {'chunks':[], 'total':0, 'version':None}
        async with app.state.blob_store.open(draft['uri']) as fp: rows = json.loads(await fp.read())
        if document.data.confirmed_chunks_version == draft.get('version') and document.status == 'ready':
            rows = [r for r in rows if r.get('metadata', {}).get('draft_change') != 'deleted']
            for i, row in enumerate(rows):
                row['chunk_index'] = i
                row['total_chunks'] = len(rows)
                row.get('metadata', {}).pop('draft_change', None)
        await app.state.knowledge_base_service.get_document(caller(request), kb_id, doc_id)
        return {'chunks': rows[(page-1)*20:page*20], 'total':len(rows), 'active_total':sum(r.get('metadata', {}).get('draft_change') != 'deleted' for r in rows), 'version':draft['version'], 'config':draft.get('config')}
