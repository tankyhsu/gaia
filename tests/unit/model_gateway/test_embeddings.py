from __future__ import annotations

import json

import httpx
import pytest

from gaia.model_gateway import OpenAICompatibleEmbeddingProvider


async def test_openai_compatible_embedding_batches_and_restores_index_order() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        requests.append(body)
        inputs = body["input"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [float(index), 1.0, 2.0]}
                    for index in reversed(range(len(inputs)))
                ]
            },
        )

    provider = OpenAICompatibleEmbeddingProvider(
        base_url="https://embedding.example/v1",
        api_key="test-key",
        model_id="embedding-model",
        expected_dimensions=3,
        request_dimensions=3,
        batch_size=2,
        transport=httpx.MockTransport(handler),
    )

    vectors = await provider.embed(["one", "two", "three"])

    assert len(requests) == 2
    assert requests[0]["dimensions"] == 3
    assert vectors == [[0.0, 1.0, 2.0], [1.0, 1.0, 2.0], [0.0, 1.0, 2.0]]


async def test_openai_compatible_embedding_rejects_bad_dimensions_and_empty_input() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})

    provider = OpenAICompatibleEmbeddingProvider(
        base_url="https://embedding.example/v1",
        api_key="test-key",
        model_id="embedding-model",
        expected_dimensions=3,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="EMBEDDING_DIMENSION_MISMATCH"):
        await provider.embed(["text"])
    with pytest.raises(ValueError, match="EMBEDDING_INPUT_EMPTY"):
        await provider.embed([""])


async def test_openai_compatible_embedding_maps_transport_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request)

    provider = OpenAICompatibleEmbeddingProvider(
        base_url="https://embedding.example/v1",
        api_key="wrong-key",
        model_id="embedding-model",
        expected_dimensions=3,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="EMBEDDING_PROVIDER_UNAVAILABLE"):
        await provider.embed(["text"])
