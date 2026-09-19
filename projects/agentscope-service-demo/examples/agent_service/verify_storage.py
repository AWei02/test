"""Offline-service persistence checks; temporary records are removed afterward."""
import asyncio
import hashlib
import json
import subprocess
from uuid import uuid4

from data_paths import DATA_ROOT, PROJECTS, QDRANT


def command(*args):
    return subprocess.check_output(args, text=True).strip()


async def vectors():
    from agentscope.rag import QdrantStore
    from qdrant_client.models import VectorParams, Distance, PointStruct
    name = 'persistence_probe_' + uuid4().hex
    store = QdrantStore(path=str(QDRANT))
    client = store.get_client()
    try:
        await client.create_collection(name, vectors_config=VectorParams(size=2, distance=Distance.COSINE))
        await client.upsert(name, [PointStruct(id=1, vector=[1.0, 0.0])], wait=True)
    finally:
        await client.close()
    other = QdrantStore(path=str(QDRANT)).get_client()
    try:
        assert (await other.count(name, exact=True)).count == 1
    finally:
        await other.delete_collection(name)
        await other.close()
    print('PASS: Qdrant close/reopen preserves vectors')


def files():
    backup = sorted((DATA_ROOT / 'backups').glob('migration-*'))[-1]
    from migrate_storage import MAPPING, manifest
    saved = json.loads((backup / 'sha256-manifest.json').read_text())
    for old, new in MAPPING.items():
        assert manifest(backup / old) == saved[old]
        if old != 'project-data':
            assert manifest(DATA_ROOT / new) == saved[old]
    # Every historical file, including unknown/deleted-directory buckets, survives.
    before = sorted(manifest(backup / 'project-data').values())
    after = sorted(manifest(PROJECTS).values())
    assert before == after
    for old in (backup / 'project-data').glob('*/files'):
        original = '/workspace/projects/agentscope-service-demo/examples/agent_service/project-data/' + old.parent.name + '/files'
        bucket = backup / 'project-data' / 'history' / hashlib.sha256(original.encode()).hexdigest()
        if bucket.exists():
            migrated = PROJECTS / 'history' / hashlib.sha256(str((PROJECTS / old.parent.name / 'files').resolve()).encode()).hexdigest()
            assert manifest(bucket) == manifest(migrated)
    print('PASS: current files, original backups and history contents verified')


def redis():
    key = '__persistence_probe__:' + uuid4().hex
    def cli(*args):
        return command('docker', 'exec', 'agentscope-redis-demo', 'redis-cli', *args)
    try:
        assert cli('SET', key, 'verified', 'EX', '600', 'NX') == 'OK'
        command('docker', 'restart', 'agentscope-redis-demo')
        assert cli('GET', key) == 'verified'
        print('PASS: Redis container restart preserves key')
        command('docker', 'compose', '-f', str(__import__('pathlib').Path(__file__).parent / 'compose.storage.yaml'), 'up', '-d', '--force-recreate')
        assert cli('GET', key) == 'verified'
        print('PASS: Redis container recreation preserves key')
    finally:
        cli('DEL', key)


if __name__ == '__main__':
    assert not command('ss', '-ltnH', 'sport = :8000'), 'Stop backend first'
    files()
    redis()
    asyncio.run(vectors())
    from fastapi.testclient import TestClient
    from main import app
    from portal import ADMIN
    with TestClient(app) as client:
        assert client.get('/health', headers={'x-user-id': ADMIN}).status_code == 200
        assert client.get('/portal/projects', headers={'x-user-id': ADMIN}).status_code == 200
    print('PASS: full service startup and shutdown')
