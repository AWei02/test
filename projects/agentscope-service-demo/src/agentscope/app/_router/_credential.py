# -*- coding: utf-8 -*-
"""Credential router — CRUD endpoints for API key credentials."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from datetime import datetime, timezone
import httpx
from urllib.parse import urlparse

from ..access import ResourceKind
from ..deps import (
    get_current_user_id,
    get_resource_access_service,
    get_storage,
)
from ._schema import (
    CreateCredentialRequest,
    CreateCredentialResponse,
    ListCredentialsResponse,
    ListCredentialSchemasResponse,
    UpdateCredentialRequest,
)
from .._service import CredentialView, ResourceAccessService
from ..storage import StorageBase
from ...credential import CredentialFactory


_MODEL_CATEGORY_ALIASES = {
    'llm': 'llm', 'language': 'llm', 'text': 'llm',
    'embedding': 'embedding', 'vector': 'embedding',
    'rerank': 'rerank', 'reranker': 'rerank',
    'vision': 'vision', 'vlm': 'vision', 'multimodal': 'vision',
    'speech': 'speech', 'audio': 'speech', 'tts': 'speech',
    'image': 'image', 'image_generation': 'image',
}

# SiliconFlow's OpenAI-compatible ``/models`` response lists IDs but does not
# provide the capability or vector dimensions needed to construct a knowledge
# base. Keep the provider's published embedding catalogue here. Unknown IDs
# remain uncategorized instead of being guessed from their names.
_SILICONFLOW_EMBEDDING_CATALOG = {
    'BAAI/bge-m3': {'category': 'embedding', 'dimensions': 1024, 'context_size': 8192},
    'Pro/BAAI/bge-m3': {'category': 'embedding', 'dimensions': 1024, 'context_size': 8192},
    'BAAI/bge-large-en-v1.5': {
        'category': 'embedding', 'dimensions': 1024, 'context_size': 512,
    },
    'BAAI/bge-large-zh-v1.5': {'category': 'embedding', 'dimensions': 1024, 'context_size': 512},
    'netease-youdao/bce-embedding-base_v1': {
        'category': 'embedding', 'dimensions': 768, 'context_size': 512,
    },
    'Qwen/Qwen3-Embedding-0.6B': {
        'category': 'embedding', 'dimensions': 1024, 'context_size': 32768,
    },
    'Qwen/Qwen3-Embedding-4B': {
        'category': 'embedding', 'dimensions': 2560, 'context_size': 32768,
    },
    'Qwen/Qwen3-Embedding-8B': {
        'category': 'embedding', 'dimensions': 4096, 'context_size': 32768,
    },
    'Qwen/Qwen3-VL-Embedding-8B': {
        'category': 'embedding', 'dimensions': 4096, 'context_size': 32768,
    },
}


def _provider_model_category(row: dict) -> str | None:
    """Accept only a capability explicitly included in a provider response."""
    for key in ('category', 'capability', 'model_category'):
        value = row.get(key)
        if isinstance(value, str):
            category = _MODEL_CATEGORY_ALIASES.get(value.strip().lower())
            if category:
                return category
    return None


def _provider_model_metadata(base_url: str, row: dict) -> dict:
    """Return explicit provider metadata; never infer from an arbitrary ID."""
    category = _provider_model_category(row)
    metadata = {'category': category} if category else {}
    if 'siliconflow.cn' in urlparse(base_url).netloc.lower():
        known = _SILICONFLOW_EMBEDDING_CATALOG.get(row['id'])
        if known:
            metadata = {**metadata, **known}
    return metadata

credential_router = APIRouter(
    prefix="/credential",
    tags=["credential"],
    responses={404: {"description": "Not found"}},
)


@credential_router.post('/{credential_id}/official-models')
async def refresh_official_models(
    credential_id: str,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> dict:
    """Read a supported OpenAI-compatible provider's live model catalog."""
    owner_id, _ = await access.resolve_for_edit(
        user_id, ResourceKind.CREDENTIAL, credential_id,
    )
    record = await storage.get_credential(owner_id, credential_id)
    if record is None:
        raise HTTPException(404, '凭据不存在')
    data = record.model_dump()['data']
    credential_type = data.get('type')
    if credential_type not in ('deepseek_credential', 'openai_credential'):
        raise HTTPException(400, '当前凭证类型不支持在线刷新模型')
    base_url = data.get(
        'base_url',
        'https://api.deepseek.com' if credential_type == 'deepseek_credential' else '',
    ).rstrip('/')
    parsed = urlparse(base_url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise HTTPException(400, 'Base URL 必须是有效的 HTTP 或 HTTPS 地址')
    if credential_type == 'deepseek_credential' and base_url not in (
        'https://api.deepseek.com', 'https://api.deepseek.com/v1',
    ):
        raise HTTPException(400, 'DeepSeek 凭证请使用官方 Base URL')
    endpoint = f"{base_url}/models"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.get(
                endpoint,
                headers={'Authorization': f"Bearer {data.get('api_key', '')}"},
            )
        if response.status_code in (401, 403):
            raise HTTPException(400, '认证失败，请检查 API Key 和账户权限')
        if response.status_code == 429:
            raise HTTPException(429, '模型接口请求过于频繁，请稍后刷新')
        if response.status_code != 200:
            raise HTTPException(502, f'模型查询失败（HTTP {response.status_code}）')
        payload = response.json()
        rows = payload['data']
        if not isinstance(rows, list) or not all(
            isinstance(row, dict) and isinstance(row.get('id'), str) for row in rows
        ):
            raise ValueError('Invalid model list')
        models = sorted({row['id'] for row in rows})
        model_metadata = {
            row['id']: metadata
            for row in rows
            if (metadata := _provider_model_metadata(base_url, row))
        }
    except httpx.TimeoutException:
        raise HTTPException(504, '连接官方接口超时，请稍后重试') from None
    except (httpx.RequestError, ValueError, KeyError, TypeError):
        raise HTTPException(502, '无法读取官方模型列表，请检查服务器网络后重试') from None
    return {
        'models': models,
        # Most OpenAI-compatible /models endpoints provide IDs only. Keep
        # categories absent unless the provider explicitly returned one.
        'model_metadata': model_metadata,
        'source': endpoint,
        'fetched_at': datetime.now(timezone.utc).isoformat(),
    }


@credential_router.get(
    "/schemas",
    response_model=ListCredentialSchemasResponse,
    summary="List JSON schemas for all credential types",
)
async def list_credential_schemas() -> ListCredentialSchemasResponse:
    """Return JSON schemas for all registered credential types.

    Used by the frontend to render credential creation forms dynamically.
    """

    return ListCredentialSchemasResponse(
        schemas=CredentialFactory.list_schemas(),
    )


@credential_router.get(
    "/",
    response_model=ListCredentialsResponse,
    summary="List all credentials",
)
async def list_credentials(
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> ListCredentialsResponse:
    """Return all credential records visible to the authenticated user.

    Includes the caller's own credentials plus any credentials shared to
    them through :class:`ResourceAccessPolicyBase`. Shared entries have
    their secret ``data`` payload masked — only the discriminator and
    display name survive in the response — while runtime resolution
    (e.g. the chat model service) still sees the full payload.

    Args:
        user_id (`str`):
            Injected authenticated user ID.
        access (`ResourceAccessService`):
            Injected resource access service.

    Returns:
        `ListCredentialsResponse`:
            All visible credentials paired with editability and
            (for shared entries) redacted data.
    """
    entries = await access.list_resource(user_id, ResourceKind.CREDENTIAL)
    return ListCredentialsResponse(
        credentials=entries,
        total=len(entries),
    )


@credential_router.post(
    "/",
    response_model=CreateCredentialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new credential",
)
async def create_credential(
    body: CreateCredentialRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> CreateCredentialResponse:
    """Store a new credential.

    Args:
        body (`CreateCredentialRequest`): Credential payload to store.
        user_id (`str`): Injected authenticated user ID.
        storage (`StorageBase`): Injected storage backend.

    Returns:
        `CreateCredentialResponse`: The server-assigned credential identifier.
    """
    credential_id = await storage.upsert_credential(
        user_id,
        CredentialFactory.from_dict(body.data),
    )
    return CreateCredentialResponse(credential_id=credential_id)


@credential_router.patch(
    "/{credential_id}",
    response_model=CredentialView,
    summary="Update a credential",
)
async def update_credential(
    credential_id: str,
    body: UpdateCredentialRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> CredentialView:
    """Replace the payload of an existing credential.

    Args:
        credential_id (`str`): The credential to update.
        body (`UpdateCredentialRequest`): New credential payload.
        user_id (`str`): Injected authenticated user ID.
        storage (`StorageBase`): Injected storage backend.
        access (`ResourceAccessService`): Injected access service — used
            to resolve the owning user and enforce the edit permission
            when a shared editor updates the credential.

    Returns:
        `CredentialView`: The updated credential record.

    Raises:
        `HTTPException`: 404 if the credential is not visible to the
            caller; 403 if visible but only readable.
    """
    owner_id, _ = await access.resolve_for_edit(
        user_id,
        ResourceKind.CREDENTIAL,
        credential_id,
    )

    credential = CredentialFactory.from_dict(body.data)
    credential.id = credential_id
    await storage.upsert_credential(owner_id, credential)
    # ``resolve_for_edit`` proved the record existed under ``owner_id``
    # and the upsert above just wrote back to the same key, so the read
    # is a value refresh, not an existence check. If it still comes back
    # empty (e.g. a concurrent delete), surface an explicit server error
    # rather than relying on ``assert`` (which ``-O`` strips).
    updated = await storage.get_credential(owner_id, credential_id)
    if updated is None:
        raise RuntimeError(
            f"Credential {credential_id!r} for owner {owner_id!r} "
            "disappeared immediately after a successful upsert.",
        )
    # Only reachable via ``resolve_for_edit``, so the caller has edit
    # permission by construction.
    return CredentialView.model_validate(
        {**updated.model_dump(), "editable": True},
    )


@credential_router.delete(
    "/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a credential",
)
async def delete_credential(
    credential_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> None:
    """Permanently delete a credential.

    Args:
        credential_id (`str`): The credential to delete.
        user_id (`str`): Injected authenticated user ID.
        storage (`StorageBase`): Injected storage backend.
        access (`ResourceAccessService`): Injected access service — used
            to resolve the owning user and enforce the edit permission
            when a shared editor deletes the credential.

    Raises:
        `HTTPException`: 404 if the credential is not visible to the
            caller; 403 if visible but only readable.
    """
    owner_id, _ = await access.resolve_for_edit(
        user_id,
        ResourceKind.CREDENTIAL,
        credential_id,
    )
    # Applications may keep authorization records outside the core resource
    # storage. Give their access policy a last chance to veto a destructive
    # delete, rather than relying only on a surrounding middleware route.
    references = getattr(
        request.app.state.resource_access_policy,
        "credential_references",
        None,
    )
    if references:
        grant_ids = references(credential_id)
        if grant_ids:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="凭证仍被访问授权引用，不能删除。授权编码：" +
                "、".join(grant_ids),
            )
    await storage.delete_credential(owner_id, credential_id)
