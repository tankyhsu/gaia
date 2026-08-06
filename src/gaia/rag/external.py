"""HTTP adapter for enterprise-managed cited retrieval services."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from gaia.spi.rag import RetrievalHit, RetrievalRequest

_HITS = TypeAdapter(tuple[RetrievalHit, ...])


class ExternalRagError(RuntimeError):
    """The configured retrieval service was unavailable or violated its contract."""


class ExternalHttpRetriever:
    """Call an existing enterprise RAG service without owning its ingestion plane."""

    def __init__(
        self,
        *,
        base_url: str,
        endpoint: str = "/v1/retrieve",
        api_key: str | None = None,
        timeout_seconds: int = 10,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._endpoint = endpoint
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def retrieve(self, request: RetrievalRequest) -> tuple[RetrievalHit, ...]:
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    self._endpoint,
                    json=request.model_dump(mode="json"),
                    headers=headers,
                )
                response.raise_for_status()
                payload: Any = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise ExternalRagError("EXTERNAL_RAG_UNAVAILABLE") from error

        raw_hits = payload.get("hits") if isinstance(payload, dict) else None
        try:
            hits = _HITS.validate_python(raw_hits)
        except ValidationError as error:
            raise ExternalRagError("EXTERNAL_RAG_INVALID_RESPONSE") from error
        if len(hits) > request.limit:
            raise ExternalRagError("EXTERNAL_RAG_LIMIT_EXCEEDED")

        allowed_permission_bases = {
            "public",
            f"user:{request.user_id}",
            *(f"role:{role}" for role in request.roles),
        }
        if any(
            hit.citation.permission_basis not in allowed_permission_bases
            for hit in hits
        ):
            raise ExternalRagError("EXTERNAL_RAG_PERMISSION_MISMATCH")
        return hits
