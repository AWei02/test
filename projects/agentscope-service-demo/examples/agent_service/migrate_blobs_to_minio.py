"""Copy legacy local knowledge blobs to MinIO and update their metadata.

Run this while the web service is stopped.  The script is deliberately
non-destructive: it does not delete files under ``AGENTSCOPE_DATA_DIR/blobs``.
Use ``--dry-run`` first, then verify document preview and retrieval before
removing the legacy directory yourself.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path

from botocore.config import Config

from agentscope.app.rag.blob_store import S3BlobStore
from agentscope.app.storage import RedisStorage

from data_paths import DATA_ROOT, PORTAL_FILE


def load_service_env() -> None:
    path = Path(__file__).with_name(".env")
    if not path.is_file():
        return
    for raw in path.read_text("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_service_env()


def build_minio() -> S3BlobStore:
    endpoint = os.getenv("MINIO_ENDPOINT", "http://127.0.0.1:9000")
    return S3BlobStore(
        bucket=os.getenv("MINIO_BUCKET", "agentscope-knowledge"),
        endpoint_url=endpoint,
        aws_access_key_id=os.getenv("MINIO_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("MINIO_SECRET_KEY"),
        use_ssl=endpoint.startswith("https://"),
        config=Config(s3={"addressing_style": "path"}),
    )


async def migrate(dry_run: bool) -> None:
    storage = RedisStorage(
        host=os.getenv("AGENTSCOPE_REDIS_HOST", "127.0.0.1"),
        port=int(os.getenv("AGENTSCOPE_REDIS_PORT", "6379")),
    )
    target = build_minio()
    moved = 0
    async with storage, target:
        # KB records are owner-scoped.  Portal users are the deployment's
        # canonical user registry, so enumerate that small, explicit list.
        portal = json.loads(PORTAL_FILE.read_text("utf-8"))
        usernames = [u["username"] for u in portal.get("users", [])]
        for username in usernames:
            for kb in await storage.list_knowledge_bases(username):
                for doc in await storage.list_knowledge_documents(username, kb.id):
                    if not doc.data.blob_uri.startswith("local://"):
                        continue
                    if dry_run:
                        print(f"would migrate {doc.id}: {doc.data.filename}")
                        moved += 1
                        continue
                    key = doc.data.blob_uri.removeprefix("local://")
                    path = (DATA_ROOT / "blobs" / key).resolve()
                    root = (DATA_ROOT / "blobs").resolve()
                    if root not in path.parents or not path.is_file():
                        raise RuntimeError(f"legacy blob is missing: {doc.id}")
                    # The S3 adapter accepts a normal file stream, so this
                    # stays memory-bounded even for large source documents.
                    with path.open("rb") as source:
                        new_uri = await target.write_stream(
                            f"kb/{kb.id}/{doc.id}", source
                        )
                    doc.data.blob_uri = new_uri
                    await storage.upsert_knowledge_document(username, doc)
                    print(f"migrated {doc.id}: {doc.data.filename}")
                    moved += 1
    print(f"{'would migrate' if dry_run else 'migrated'} {moved} document(s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(migrate(args.dry_run))
