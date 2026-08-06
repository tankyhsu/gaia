from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from gaia.observability import OpenTelemetryModelInvocationSink
from gaia.observability.models import ModelInvocation, ModelInvocationStatus
from gaia.spi.model import ModelUsage


class Span:
    def __init__(self) -> None:
        self.end_time: int | None = None

    def end(self, *, end_time: int) -> None:
        self.end_time = end_time


class Tracer:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}
        self.span = Span()

    def start_span(
        self,
        name: str,
        *,
        attributes: dict[str, object],
        start_time: int,
    ) -> Span:
        assert name == "gaia.model.generate"
        assert start_time > 0
        self.attributes = attributes
        return self.span


class Instrument:
    def __init__(self) -> None:
        self.values: list[tuple[int, dict[str, object]]] = []

    def add(self, value: int, attributes: dict[str, object]) -> None:
        self.values.append((value, attributes))

    def record(self, value: int, attributes: dict[str, object]) -> None:
        self.values.append((value, attributes))


class Meter:
    def __init__(self) -> None:
        self.instruments: dict[str, Instrument] = {}

    def create_counter(self, name: str, **kwargs: Any) -> Instrument:
        del kwargs
        self.instruments[name] = Instrument()
        return self.instruments[name]

    def create_histogram(self, name: str, **kwargs: Any) -> Instrument:
        del kwargs
        self.instruments[name] = Instrument()
        return self.instruments[name]


async def test_otel_sink_emits_only_safe_attributes_and_metrics() -> None:
    started = datetime.now(UTC)
    tracer = Tracer()
    meter = Meter()
    sink = OpenTelemetryModelInvocationSink(tracer, meter)
    await sink.record(
        ModelInvocation(
            invocation_id="inv-1",
            run_id="run-1",
            scenario_id="summary",
            provider="mock",
            model_id="model",
            model_parameters_hash="sha256:parameters",
            prompt_version="summary:1.0.0",
            request_ref="sha256:request",
            response_ref="sha256:response",
            status=ModelInvocationStatus.SUCCEEDED,
            usage=ModelUsage(
                input_tokens=8,
                output_tokens=2,
                total_tokens=10,
                estimated_cost=0.001,
                currency="USD",
            ),
            started_at=started,
            completed_at=started + timedelta(milliseconds=12),
            duration_ms=12,
        )
    )

    assert tracer.attributes["gaia.run.id"] == "run-1"
    assert tracer.attributes["langfuse.observation.type"] == "generation"
    assert tracer.attributes["langfuse.observation.model.name"] == "model"
    assert tracer.attributes["gen_ai.usage.input_tokens"] == 8
    assert tracer.attributes["gen_ai.usage.output_tokens"] == 2
    assert tracer.attributes["gen_ai.usage.cost"] == 0.001
    assert tracer.attributes["langfuse.observation.usage_details"] == (
        '{"input":8,"output":2,"total":10}'
    )
    assert tracer.attributes["langfuse.observation.cost_details"] == (
        '{"total":0.001}'
    )
    assert tracer.attributes["langfuse.observation.metadata.prompt_version"] == (
        "summary:1.0.0"
    )
    assert "request_ref" not in tracer.attributes
    assert "response_ref" not in tracer.attributes
    assert "langfuse.observation.input" not in tracer.attributes
    assert "langfuse.observation.output" not in tracer.attributes
    assert meter.instruments["gaia.model.calls"].values[0][0] == 1
    assert [item[0] for item in meter.instruments["gaia.model.tokens"].values] == [8, 2]
