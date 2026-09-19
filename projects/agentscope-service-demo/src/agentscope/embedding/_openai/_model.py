# -*- coding: utf-8 -*-
"""The OpenAI embedding model."""
from __future__ import annotations

from datetime import datetime
import asyncio
import math
from urllib.parse import urlsplit
from typing import Any, Type

from .._embedding_response import EmbeddingResponse
from .._embedding_usage import EmbeddingUsage
from .._cache_base import EmbeddingCacheBase
from .._embedding_base import EmbeddingModelBase
from ...credential import CredentialBase
from ...message import TextBlock


class OpenAIEmbeddingModel(EmbeddingModelBase[str | TextBlock]):
    """OpenAI text embedding model.

    Supports ``text-embedding-3-small``, ``text-embedding-3-large``,
    and other OpenAI-compatible embedding models.  Inherits batching
    and retry logic from :class:`EmbeddingModelBase`.  ``TextBlock``
    items in the input list are unpacked to their ``.text`` field by
    the base class before ``_call_api`` runs, so this subclass only
    has to handle plain ``str``.
    """

    #: OpenAI does not document an explicit per-request item limit;
    #: the constraint is on total tokens.  We use a conservative
    #: default that works well in practice.
    _TEXT_BATCH_SIZE: int = 2048

    def __init__(
        self,
        credential: CredentialBase,
        model: str,
        dimensions: int | None,
        parameters: "OpenAIEmbeddingModel.Parameters | None" = None,
        pass_dimensions: bool = True,
        embedding_cache: EmbeddingCacheBase | None = None,
        context_size: int = 8191,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        """Initialize the OpenAI embedding model.

        Args:
            credential (`CredentialBase`):
                An :class:`~agentscope.credential.OpenAICredential`
                instance providing the API key and optional base URL /
                organization.
            model (`str`):
                The embedding model name (e.g.
                ``"text-embedding-3-small"``).
            dimensions (`int | None`):
                The output embedding vector dimensions.  Required at
                the contract level — see :class:`EmbeddingModelBase`
                for the rationale.  ``None`` is accepted only for
                backward compatibility with legacy configs that
                persisted ``dimensions`` inside ``parameters``.
            parameters (`OpenAIEmbeddingModel.Parameters | None`, \
            defaults to ``None``):
                Provider-specific non-dimensional parameters.  Currently
                empty for OpenAI.
            pass_dimensions (`bool`, defaults to `True`):
                Whether to pass the ``dimensions`` parameter to the API.
                Some OpenAI-compatible providers do not support it.
            embedding_cache (`EmbeddingCacheBase | None`, defaults to \
            ``None``):
                Optional embedding cache.
            context_size (`int`, defaults to ``8191``):
                Maximum input tokens per text.
            max_retries (`int`, defaults to ``3``):
                Number of retries on transient failures.
            retry_delay (`float`, defaults to ``1.0``):
                Seconds between retry attempts.
        """
        import openai

        super().__init__(
            credential=credential,
            model=model,
            dimensions=dimensions,
            parameters=parameters,
            context_size=context_size,
            batch_size=self._TEXT_BATCH_SIZE,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

        client_kwargs: dict[str, Any] = {}
        if getattr(credential, "base_url", None) is not None:
            client_kwargs["base_url"] = credential.base_url
        if getattr(credential, "organization", None) is not None:
            client_kwargs["organization"] = credential.organization

        self.client: openai.AsyncClient = openai.AsyncClient(
            api_key=credential.api_key.get_secret_value(),
            **client_kwargs,
        )
        self.pass_dimensions = pass_dimensions
        self.embedding_cache: EmbeddingCacheBase | None = embedding_cache
        # Compatible services need not support OpenAI's large request batches.
        # SiliconFlow Qwen3-VL currently repeats indices across groups of eight.
        if urlsplit(str(self.client.base_url)).hostname != 'api.openai.com':
            self.batch_size = 8
        self._request_semaphore = asyncio.Semaphore(4)

    @classmethod
    def _get_retryable_exceptions(cls) -> tuple[Type[Exception], ...]:
        """Return OpenAI exceptions that warrant a retry."""
        import openai

        return (
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.RateLimitError,
            openai.InternalServerError,
        )

    async def _call_api(
        self,
        inputs: list[str],
        **kwargs: Any,
    ) -> EmbeddingResponse:
        """Call the OpenAI embedding API for a single batch.

        Args:
            inputs (`list[str]`):
                A batch of texts to embed.
            **kwargs:
                Extra keyword arguments forwarded to the OpenAI API.

        Returns:
            `EmbeddingResponse`: Embedding vectors and usage info.
        """
        api_kwargs: dict[str, Any] = {
            "input": inputs,
            "model": self.model,
            "encoding_format": "float",
            **kwargs,
        }
        if self.pass_dimensions:
            api_kwargs["dimensions"] = self.dimensions

        if self.embedding_cache:
            cached = await self.embedding_cache.retrieve(
                identifier=api_kwargs,
            )
            if cached and self._valid_vectors(cached, len(inputs)):
                return EmbeddingResponse(
                    embeddings=cached,
                    usage=EmbeddingUsage(tokens=0, time=0),
                    source="cache",
                )

        start_time = datetime.now()
        async with self._request_semaphore:
            response = await self.client.embeddings.create(**api_kwargs)
        time = (datetime.now() - start_time).total_seconds()

        embeddings: list[Any] = [None] * len(inputs)
        seen = set()
        valid_indices = len(response.data) == len(inputs)
        for pos, item in enumerate(response.data):
            index = getattr(item, "index", pos)
            if type(index) is not int or index in seen or not 0 <= index < len(inputs):
                valid_indices = False
            else:
                seen.add(index)
                embeddings[index] = item.embedding or getattr(
                    item,
                    "dense_embedding",
                    None,
                )

        if not valid_indices or not self._valid_vectors(embeddings, len(inputs)):
            # Never guess positional correspondence for duplicate/missing indices.
            # Reissue smaller batches so each vector has an unambiguous input.
            if len(inputs) > 1:
                middle = len(inputs) // 2
                parts = [await self._call_api(inputs[:middle], **kwargs),
                         await self._call_api(inputs[middle:], **kwargs)]
                return self._merge_responses(parts)
            raise RuntimeError('向量服务返回空向量、错误维度或无效索引；未写入向量库，请检查模型配置。')

        if self.embedding_cache:
            await self.embedding_cache.store(
                identifier=api_kwargs,
                embeddings=embeddings,
            )

        return EmbeddingResponse(
            embeddings=embeddings,
            usage=EmbeddingUsage(
                tokens=response.usage.total_tokens,
                time=time,
            ),
        )

    def _valid_vectors(self, vectors, count):
        return len(vectors) == count and all(
            isinstance(v, list) and len(v) == self.dimensions and
            all(type(n) in (int, float) and math.isfinite(n) for n in v)
            for v in vectors)
