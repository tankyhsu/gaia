"""Langfuse OTLP bootstrap shared by Temporal and model instrumentation."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from gaia.config.models import ObservabilitySettings
from gaia.config.secrets import resolve_secret


@dataclass(frozen=True)
class LangfuseTelemetry:
    """One tracer provider shared by Gaia model spans and Temporal interceptors."""

    tracer: Any
    meter: Any
    temporal_interceptor: Any
    tracer_provider: Any
    endpoint: str


def langfuse_otlp_endpoint(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/public/otel/v1/traces"


def langfuse_headers(public_key: str, secret_key: str) -> dict[str, str]:
    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "x-langfuse-ingestion-version": "4",
    }


def build_langfuse_telemetry(
    settings: ObservabilitySettings,
    *,
    service_name: str,
    service_version: str,
) -> LangfuseTelemetry | None:
    """Create an isolated OTLP pipeline; return no-op selection for local mode."""

    if settings.provider != "langfuse":
        return None
    if settings.public_key is None or settings.secret_key is None:
        raise ValueError("LANGFUSE_CREDENTIALS_REQUIRED")

    try:
        from opentelemetry import metrics
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
        from temporalio.contrib.opentelemetry import TracingInterceptor
    except ImportError as error:
        raise RuntimeError(
            "Langfuse integration requires the 'langfuse' optional dependency"
        ) from error

    public_key = resolve_secret(settings.public_key)
    secret_key = resolve_secret(settings.secret_key)
    endpoint = langfuse_otlp_endpoint(settings.base_url)
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": service_name,
                "service.version": service_version,
                "deployment.environment.name": settings.environment,
            }
        ),
        sampler=TraceIdRatioBased(settings.sample_rate),
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=endpoint,
                headers=langfuse_headers(public_key, secret_key),
            )
        )
    )
    tracer = provider.get_tracer("gaia")
    return LangfuseTelemetry(
        tracer=tracer,
        meter=metrics.get_meter("gaia"),
        temporal_interceptor=TracingInterceptor(tracer),
        tracer_provider=provider,
        endpoint=endpoint,
    )
