from pathlib import Path
from types import SimpleNamespace

from examples.controlled_task import app as controlled_app
from examples.controlled_task.app import CONFIG_PATH, _dependencies, application_config_path
from gaia.application import GaiaApplication
from gaia.config.models import ObservabilitySettings
from gaia.persistence.database import dispose_session_factory, initialize_database
from gaia.runtime.temporal_runtime import TemporalRuntimeEngine


async def test_controlled_task_public_app_assembles_only_temporal(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/controlled-task.db"
    factory = await initialize_database(database_url)
    try:
        config = GaiaApplication.from_config(CONFIG_PATH).config
        dependencies = _dependencies(config, database_url)
        assert dependencies.lifespan is not None
        async with dependencies.lifespan():
            runtime = dependencies.runtime_factory(
                factory,
                database_url,
            )
            assert isinstance(runtime, TemporalRuntimeEngine)
    finally:
        await dispose_session_factory(factory)


def test_controlled_task_honors_canonical_config_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = tmp_path / "production-like.yaml"
    config.write_text("gaia: {}\n")
    monkeypatch.setenv("GAIA_CONFIG_PATH", str(config))

    assert application_config_path() == config.resolve()


async def test_controlled_task_wires_langfuse_into_client_and_worker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class Meter:
        def create_counter(self, *args, **kwargs):
            return object()

        def create_histogram(self, *args, **kwargs):
            return object()

    database_url = f"sqlite+aiosqlite:///{tmp_path}/controlled-task.db"
    factory = await initialize_database(database_url)
    interceptor = object()
    monkeypatch.setattr(
        controlled_app,
        "build_langfuse_telemetry",
        lambda settings, **kwargs: SimpleNamespace(
            tracer=object(),
            meter=Meter(),
            temporal_interceptor=interceptor,
        ),
    )
    try:
        config = GaiaApplication.from_config(CONFIG_PATH).config.model_copy(
            update={
                "observability": ObservabilitySettings(
                    provider="langfuse",
                    public_key={"env": "LANGFUSE_PUBLIC_KEY"},
                    secret_key={"env": "LANGFUSE_SECRET_KEY"},
                )
            }
        )
        dependencies = _dependencies(config, database_url)
        assert dependencies.lifespan is not None
        async with dependencies.lifespan():
            runtime = dependencies.runtime_factory(
                factory,
                database_url,
            )
            assert isinstance(runtime, TemporalRuntimeEngine)
            assert runtime.temporal_interceptors == (interceptor,)
    finally:
        await dispose_session_factory(factory)
