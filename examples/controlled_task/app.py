"""ASGI composition root for the controlled-task reference application."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gaia.api.app import ApiDependencies
from gaia.api.app import create_app as create_framework_app
from gaia.application import GaiaApplication
from gaia.config import GaiaApplicationConfig
from gaia.contracts.models import ModelHealth
from gaia.evals.replay import JsonReplayFixtureSource, ReplayRunner
from gaia.model_gateway import embedding_function_from_config
from gaia.observability import InstrumentedModelProvider, SqlAlchemyModelInvocationStore
from gaia.persistence import GaiaPersistenceResources
from gaia.runtime.persistent_engine import PersistentRuntimeEngine

from .composition import create_controlled_task_composition
from .model import DeterministicMockProvider
from .runner import model_profile
from .workflow import build_controlled_task_graph

CASES_PATH = Path(__file__).parent / "specs" / "acceptance-cases.json"
CONFIG_PATH = Path(__file__).parent / "gaia.yaml"


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
    ) -> PersistentRuntimeEngine:
        composition = create_controlled_task_composition(
            workflow=build_controlled_task_graph(resources.checkpointer),
            environment=config.runtime.environment,
            environment_write_mode=config.runtime.effective_write_mode(),
            model_provider=InstrumentedModelProvider(
                DeterministicMockProvider(),
                SqlAlchemyModelInvocationStore(factory),
            ),
        )
        return composition.create_runtime(factory)

    def replay_factory(factory: async_sessionmaker[AsyncSession]) -> ReplayRunner:
        return ReplayRunner(
            factory,
            JsonReplayFixtureSource(CASES_PATH),
            create_controlled_task_composition,
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
    gaia_application = GaiaApplication.from_config(CONFIG_PATH)
    return create_framework_app(
        database_url=database_url,
        api_key=api_key,
        dependencies=_dependencies(gaia_application.config, database_url),
        gaia_application=gaia_application,
        sse_poll_interval_seconds=sse_poll_interval_seconds,
        sse_heartbeat_seconds=sse_heartbeat_seconds,
    )
