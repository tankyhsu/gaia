from __future__ import annotations

import os

import pytest

from gaia.model_gateway import OpenAICompatibleEmbeddingProvider

API_KEY = os.environ.get("SILICONFLOW_API_KEY")
RUN_EXTERNAL_TESTS = os.environ.get("RUN_EXTERNAL_TESTS") == "1"
pytestmark = [
    pytest.mark.external,
    pytest.mark.skipif(
        not RUN_EXTERNAL_TESTS or not API_KEY,
        reason="RUN_EXTERNAL_TESTS=1 and SILICONFLOW_API_KEY are required",
    ),
]


async def test_siliconflow_returns_configured_embedding_dimensions() -> None:
    assert API_KEY is not None
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="https://api.siliconflow.cn/v1",
        api_key=API_KEY,
        model_id="Qwen/Qwen3-Embedding-0.6B",
        expected_dimensions=64,
        request_dimensions=64,
        batch_size=8,
        timeout_seconds=30,
    )

    vectors = await provider.embed(["企业知识库", "设备故障维修"])

    assert len(vectors) == 2
    assert all(len(vector) == 64 for vector in vectors)
    assert vectors[0] != vectors[1]
