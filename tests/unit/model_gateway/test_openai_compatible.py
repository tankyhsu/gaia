from __future__ import annotations

import json

import httpx
import respx
from pydantic import BaseModel

from gaia.contracts.models import ModelCapabilities, ModelEndpointProfile
from gaia.model_gateway import OpenAICompatibleProvider
from gaia.observability import InstrumentedModelProvider
from gaia.observability.models import ModelInvocation
from gaia.spi.model import ModelCallContext, ModelMessage


class Answer(BaseModel):
    answer: str


class RecordingSink:
    def __init__(self) -> None:
        self.items: list[ModelInvocation] = []

    async def record(self, invocation: ModelInvocation) -> None:
        self.items.append(invocation)


async def test_openai_compatible_provider_uses_common_observation_contract() -> None:
    sink = RecordingSink()
    provider = InstrumentedModelProvider(
        OpenAICompatibleProvider(api_key="test-key"),
        sink,
    )
    profile = ModelEndpointProfile(
        provider_id="openai-compatible",
        protocol="openai-compatible",
        base_url="https://models.example/v1",
        model_id="enterprise-model",
        capabilities=ModelCapabilities(
            structured_output=True,
            tool_calling=False,
            streaming=False,
            max_context_tokens=8192,
        ),
        data_residency="external",
        timeout_seconds=2,
    )
    with respx.mock() as router:
        route = router.post("https://models.example/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "provider-response-id",
                    "choices": [{"message": {"content": '{"answer":"ok"}'}}],
                    "usage": {
                        "prompt_tokens": 11,
                        "completion_tokens": 2,
                        "total_tokens": 13,
                    },
                },
            )
        )
        result = await provider.generate_structured(
            profile=profile,
            messages=[ModelMessage(role="user", content="customer content")],
            output_schema=Answer,
            timeout_seconds=2,
            context=ModelCallContext(
                run_id="run-openai",
                scenario_id="summarize",
                prompt_version="summarize:3.0.0",
            ),
        )

    assert route.called
    request_body = json.loads(route.calls.last.request.content)
    assert request_body["messages"][0]["role"] == "system"
    assert "JSON Schema" in request_body["messages"][0]["content"]
    assert request_body["messages"][1] == {
        "role": "user",
        "content": "customer content",
    }
    assert request_body["response_format"] == {"type": "json_object"}
    assert result.usage is not None
    assert result.usage.total_tokens == 13
    assert sink.items[0].usage == result.usage
    assert sink.items[0].provider == "openai-compatible"
    assert "customer content" not in sink.items[0].model_dump_json()


async def test_openai_compatible_provider_streams_deltas_and_records_invocation() -> None:
    sink = RecordingSink()
    provider = InstrumentedModelProvider(
        OpenAICompatibleProvider(api_key="test-key"),
        sink,
    )
    profile = ModelEndpointProfile(
        provider_id="openai-compatible",
        protocol="openai-compatible",
        base_url="https://models.example/v1",
        model_id="enterprise-model",
        capabilities=ModelCapabilities(
            structured_output=True,
            tool_calling=False,
            streaming=True,
            max_context_tokens=8192,
        ),
        data_residency="external",
        timeout_seconds=2,
    )
    stream_body = "\n\n".join(
        [
            'data: {"id":"response-1","model":"enterprise-model","choices":'
            '[{"delta":{"content":"Hel"},"finish_reason":null}]}',
            'data: {"id":"response-1","model":"enterprise-model","choices":'
            '[{"delta":{"content":"lo"},"finish_reason":"stop"}]}',
            'data: {"id":"response-1","model":"enterprise-model","choices":[],'
            '"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6}}',
            "data: [DONE]",
        ]
    )
    with respx.mock() as router:
        route = router.post("https://models.example/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                text=stream_body,
                headers={"content-type": "text/event-stream"},
            )
        )
        chunks = [
            chunk
            async for chunk in provider.generate_stream(
                profile=profile,
                messages=[ModelMessage(role="user", content="customer content")],
                timeout_seconds=2,
                context=ModelCallContext(
                    run_id="run-stream",
                    scenario_id="chat",
                    prompt_version="chat:1.0.0",
                ),
            )
        ]

    assert route.called
    assert "".join(chunk.delta for chunk in chunks) == "Hello"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.total_tokens == 6
    assert sink.items[0].status.value == "succeeded"
    assert sink.items[0].usage is not None
    assert sink.items[0].first_token_latency_ms is not None
    assert "customer content" not in sink.items[0].model_dump_json()
    assert "Hello" not in sink.items[0].model_dump_json()
