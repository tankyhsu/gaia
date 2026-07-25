"""OpenAI-compatible embedding provider."""

from __future__ import annotations

import math
from collections.abc import Sequence

import httpx
from pydantic import BaseModel, ConfigDict

from gaia.config import GaiaApplicationConfig, resolve_secret
from gaia.sdk.embedding import EmbeddingFunction


class _EmbeddingData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int
    embedding: list[float]


class _EmbeddingResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: list[_EmbeddingData]


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_id: str,
        expected_dimensions: int,
        request_dimensions: int | None = None,
        batch_size: int = 32,
        timeout_seconds: int = 30,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_id = model_id
        self._expected_dimensions = expected_dimensions
        self._request_dimensions = request_dimensions
        self._batch_size = batch_size
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        inputs = list(texts)
        if not inputs:
            return []
        if any(not value.strip() for value in inputs):
            raise ValueError("EMBEDDING_INPUT_EMPTY")
        result: list[list[float]] = []
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            transport=self._transport,
        ) as client:
            for offset in range(0, len(inputs), self._batch_size):
                result.extend(
                    await self._request(client, inputs[offset : offset + self._batch_size])
                )
        return result

    async def _request(self, client: httpx.AsyncClient, inputs: list[str]) -> list[list[float]]:
        body: dict[str, object] = {
            "model": self._model_id,
            "input": inputs,
            "encoding_format": "float",
        }
        if self._request_dimensions is not None:
            body["dimensions"] = self._request_dimensions
        try:
            response = await client.post(
                "/embeddings",
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise RuntimeError("EMBEDDING_PROVIDER_UNAVAILABLE") from error
        payload = _EmbeddingResponse.model_validate(response.json())
        ordered = sorted(payload.data, key=lambda item: item.index)
        if [item.index for item in ordered] != list(range(len(inputs))):
            raise RuntimeError("EMBEDDING_RESPONSE_INDEX_INVALID")
        vectors = [item.embedding for item in ordered]
        if any(len(vector) != self._expected_dimensions for vector in vectors):
            raise RuntimeError("EMBEDDING_DIMENSION_MISMATCH")
        if any(not math.isfinite(value) for vector in vectors for value in vector):
            raise RuntimeError("EMBEDDING_VALUE_INVALID")
        return vectors


def embedding_function_from_config(
    config: GaiaApplicationConfig,
) -> EmbeddingFunction | None:
    settings = config.embedding
    if settings.provider == "disabled":
        return None
    if settings.base_url is None or settings.api_key is None:
        raise ValueError("EMBEDDING_PROVIDER_CONFIGURATION_REQUIRED")
    api_key = resolve_secret(settings.api_key)
    if not api_key.strip():
        raise ValueError("EMBEDDING_API_KEY_REQUIRED")
    provider = OpenAICompatibleEmbeddingProvider(
        base_url=settings.base_url,
        api_key=api_key,
        model_id=settings.model_id,
        expected_dimensions=config.stores.vector.dimensions,
        request_dimensions=settings.dimensions,
        batch_size=settings.batch_size,
        timeout_seconds=settings.timeout_seconds,
    )
    return provider.embed
