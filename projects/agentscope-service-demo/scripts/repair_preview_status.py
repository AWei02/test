"""Repair only indexed preview drafts in the user's explicitly reported KB."""
import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4
import httpx
from agentscope.app.storage import RedisStorage

KB = '397c349e6a1346b4ad7150d7df5b610a'
OWNER = 'wei'

async def main():
    pid = int(sys.argv[1])
    proc = Path('/proc') / str(pid)
    assert (proc/'cwd').resolve() == Path('/workspace/projects/agentscope-service-demo/examples/agent_service')
    env = dict(v.decode().split('=', 1) for v in (proc/'environ').read_bytes().split(b'\0') if b'=' in v)
    async with RedisStorage(host=env.get('AGENTSCOPE_REDIS_HOST','127.0.0.1'), port=int(env.get('AGENTSCOPE_REDIS_PORT','6379'))) as storage:
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8000', headers={'X-User-ID':OWNER}, timeout=30) as client:
            for doc in await storage.list_knowledge_documents(OWNER, KB):
                if not (doc.status == 'awaiting_chunk_confirmation' and doc.data.stage_action == 'chunk' and doc.data.chunk_count > 0):
                    continue
                r = await client.get(f'/knowledge_bases/{KB}/documents/{doc.id}/chunks')
                r.raise_for_status()
                indexed = r.json()
                assert indexed.get('chunks'), 'No physical indexed chunks; do not infer readiness from count alone'
                print(doc.id, doc.data.filename, doc.status, 'indexed', doc.data.chunk_count)
                if '--apply' not in sys.argv:
                    continue
                node = 'repair-preview:' + uuid4().hex
                assert await storage.acquire_knowledge_document_lease(OWNER, KB, doc.id, node, timedelta(seconds=30))
                try:
                    fresh = await storage.get_knowledge_document(OWNER, KB, doc.id)
                    assert fresh.status == doc.status and fresh.data.stage_action == 'chunk' and fresh.data.chunk_count == doc.data.chunk_count
                    fresh.status = 'ready'
                    await storage.upsert_knowledge_document(OWNER, fresh)
                    print('Restored ready; draft, vectors and indexed count unchanged')
                finally:
                    await storage.release_knowledge_document_lease(OWNER, KB, doc.id, node)

asyncio.run(main())
