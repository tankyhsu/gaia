"""ASGI composition root for the controlled-task reference application."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gaia.api.app import ApiDependencies
from gaia.api.app import create_app as create_framework_app
from gaia.application import GaiaApplication
from gaia.config import GaiaApplicationConfig, resolve_config_path
from gaia.contracts.models import ModelHealth
from gaia.evals.replay import JsonReplayFixtureSource, ReplayRunner
from gaia.model_gateway import embedding_function_from_config
from gaia.observability import InstrumentedModelProvider, SqlAlchemyModelInvocationStore
from gaia.observability.langfuse import build_langfuse_telemetry
from gaia.observability.model_provider import CompositeModelInvocationSink
from gaia.observability.opentelemetry import OpenTelemetryModelInvocationSink
from gaia.persistence import GaiaPersistenceResources
from gaia.persistence.audit import SqlAlchemyAuditProjection
from gaia.runtime.temporal_backend import TemporalClientBackend
from gaia.runtime.temporal_runtime import TemporalRuntimeEngine

from .composition import create_controlled_task_composition
from .model import DeterministicMockProvider
from .runner import model_profile
from .workflow import build_controlled_task_graph

CASES_PATH = Path(__file__).parent / "specs" / "acceptance-cases.json"
CONFIG_PATH = Path(__file__).parent / "gaia.yaml"


def application_config_path() -> Path:
    return (
        resolve_config_path()
        if os.environ.get("GAIA_CONFIG_PATH")
        else CONFIG_PATH.resolve()
    )


def _dependencies(
    config: GaiaApplicationConfig, database_url: str | None = None
) -> ApiDependencies:
    resources = GaiaPersistenceResources(
        config,
        embed=embedding_function_from_config(config),
        database_url=database_url,
    )

    def runtime_factory(
        factory: async_sessionmaker[AsyncSession], database_url: str
    ) -> TemporalRuntimeEngine:
        del database_url
        telemetry = build_langfuse_telemetry(
            config.observability,
            service_name=config.application.name,
            service_version=config.application.version,
        )
        model_sinks = [SqlAlchemyModelInvocationStore(factory)]
        if telemetry is not None:
            model_sinks.append(
                OpenTelemetryModelInvocationSink(
                    telemetry.tracer,
                    telemetry.meter,
                )
            )
        audit_projection = SqlAlchemyAuditProjection(factory)
        composition = create_controlled_task_composition(
            workflow=build_controlled_task_graph(resources.checkpointer),
            environment=config.runtime.environment,
            environment_write_mode=config.runtime.effective_write_mode(),
            audit_projection=audit_projection,
            model_provider=InstrumentedModelProvider(
                DeterministicMockProvider(),
                CompositeModelInvocationSink(model_sinks),
            ),
        )
        temporal_interceptors = (
            () if telemetry is None else (telemetry.temporal_interceptor,)
        )
        return TemporalRuntimeEngine(
            execution=config.runtime.execution,
            backend=TemporalClientBackend(
                config.runtime.execution,
                interceptors=temporal_interceptors,
            ),
            dependencies=composition.dependencies,
            human_gate_ttl_seconds=config.policy.human_gate_ttl_seconds,
            temporal_interceptors=temporal_interceptors,
            audit_projection=audit_projection,
            reason=(
                "The controlled-task reference application uses Temporal as its "
                "only durable execution owner."
            ),
        )

    def replay_factory(factory: async_sessionmaker[AsyncSession]) -> ReplayRunner:
        return ReplayRunner(
            factory,
            JsonReplayFixtureSource(CASES_PATH),
            lambda: runtime_factory(factory, database_url or ""),
        )

    async def model_health() -> ModelHealth:
        return await DeterministicMockProvider().health(model_profile())

    return ApiDependencies(
        runtime_factory=runtime_factory,
        replay_factory=replay_factory,
        model_health=model_health,
        lifespan=resources.lifespan,
    )


def create_app(
    database_url: str | None = None,
    api_key: str | None = None,
    *,
    sse_poll_interval_seconds: float | None = None,
    sse_heartbeat_seconds: float | None = None,
) -> FastAPI:
    gaia_application = GaiaApplication.from_config(application_config_path())
    return create_framework_app(
        database_url=database_url,
        api_key=api_key,
        dependencies=_dependencies(gaia_application.config, database_url),
        gaia_application=gaia_application,
        sse_poll_interval_seconds=sse_poll_interval_seconds,
        sse_heartbeat_seconds=sse_heartbeat_seconds,
    )
