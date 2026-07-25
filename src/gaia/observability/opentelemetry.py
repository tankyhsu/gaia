"""Optional OpenTelemetry exporter for safe model invocation attributes."""

from __future__ import annotations

import importlib
from typing import Any

from gaia.observability.models import ModelInvocation


class OpenTelemetryModelInvocationSink:
    """Emit spans and metrics through an application-supplied OpenTelemetry API."""

    def __init__(self, tracer: Any, meter: Any) -> None:
        self._tracer = tracer
        self._calls = meter.create_counter(
            "gaia.model.calls",
            description="Logical model calls",
        )
        self._duration = meter.create_histogram(
            "gaia.model.duration",
            unit="ms",
            description="Logical model call duration",
        )
        self._tokens = meter.create_counter(
            "gaia.model.tokens",
            description="Provider-reported model tokens",
        )

    @classmethod
    def from_installed_api(
        cls,
        *,
        instrumentation_name: str = "gaia.model",
    ) -> OpenTelemetryModelInvocationSink:
        try:
            metrics = importlib.import_module("opentelemetry.metrics")
            trace = importlib.import_module("opentelemetry.trace")
        except ImportError as error:
            raise RuntimeError(
                "OpenTelemetry integration requires the 'otel' optional dependency"
            ) from error
        return cls(
            trace.get_tracer(instrumentation_name),
            metrics.get_meter(instrumentation_name),
        )

    async def record(self, invocation: ModelInvocation) -> None:
        attributes: dict[str, str | int] = {
            "gaia.run.id": invocation.run_id,
            "gaia.scenario.id": invocation.scenario_id,
            "gen_ai.provider.name": invocation.provider,
            "gen_ai.request.model": invocation.model_id,
            "gaia.prompt.version": invocation.prompt_version,
            "gaia.model.status": invocation.status.value,
            "gaia.model.retry_count": invocation.retry_count,
        }
        if invocation.error_code is not None:
            attributes["error.type"] = invocation.error_code
        span = self._tracer.start_span(
            "gaia.model.generate",
            attributes=attributes,
            start_time=_nanoseconds(invocation.started_at.timestamp()),
        )
        span.end(end_time=_nanoseconds(invocation.completed_at.timestamp()))
        self._calls.add(1, attributes)
        self._duration.record(invocation.duration_ms, attributes)
        if invocation.usage is not None:
            self._tokens.add(
                invocation.usage.input_tokens,
                {**attributes, "gen_ai.token.type": "input"},
            )
            self._tokens.add(
                invocation.usage.output_tokens,
                {**attributes, "gen_ai.token.type": "output"},
            )


def _nanoseconds(seconds: float) -> int:
    return round(seconds * 1_000_000_000)
