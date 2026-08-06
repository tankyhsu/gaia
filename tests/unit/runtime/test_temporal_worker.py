from __future__ import annotations

import pytest
from pydantic import ValidationError
from temporalio.common import VersioningBehavior

from gaia.config.models import RuntimeExecutionSettings
from gaia.runtime.temporal_runtime import (
    TemporalRuntimeEngine,
    TemporalRuntimeUnavailable,
)
from gaia.runtime.temporal_worker import (
    TemporalWorkerProfile,
    TemporalWorkerProfileError,
    build_temporal_entrypoint_kwargs,
    build_temporal_worker,
    build_temporal_worker_profile,
)
from gaia.runtime.temporal_workflow import GaiaRuntimeWorkflow


def test_temporal_worker_profile_parses_bracketed_ipv6() -> None:
    profile = build_temporal_worker_profile(
        execution=RuntimeExecutionSettings(server_address="[::1]:7233")
    )

    assert profile.host == "::1"
    assert profile.port == 7233


def test_temporal_worker_profile_defaults_port_when_missing() -> None:
    profile = build_temporal_worker_profile(
        execution=RuntimeExecutionSettings(server_address="127.0.0.1")
    )

    assert profile.host == "127.0.0.1"
    assert profile.port == 7233


def test_temporal_worker_profile_invalid_server_is_rejected() -> None:
    with pytest.raises(TemporalWorkerProfileError):
        build_temporal_worker_profile(
            execution=RuntimeExecutionSettings(server_address="bad host:bad")
        )


def test_temporal_worker_entrypoint_profile_shape() -> None:
    profile = build_temporal_worker_profile(
        execution=RuntimeExecutionSettings(
            server_address="localhost:7233", task_queue="gaia-runtime"
        )
    )
    plan = TemporalWorkerProfile.from_execution_settings(
        RuntimeExecutionSettings(server_address="localhost:7233", task_queue="gaia-runtime")
    )

    assert profile.task_queue == plan.task_queue
    assert profile.server_address == plan.server_address
    assert isinstance(profile.worker_kwargs(), dict)
    assert profile.worker_kwargs()["task_queue"] == "gaia-runtime"


def test_temporal_worker_entrypoint_builds_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "gaia.runtime.temporal_worker.ensure_temporal_runtime_available",
        lambda: None,
    )

    entrypoint = build_temporal_entrypoint_kwargs(
        execution=RuntimeExecutionSettings(
            server_address="localhost:7233", task_queue="gaia-runtime"
        ),
        workflows=(int,),
        activities=(str,),
    )

    assert entrypoint["connection"]["target"] == "localhost:7233"
    assert entrypoint["connection"]["tls"] is False
    assert entrypoint["worker"]["task_queue"] == "gaia-runtime"
    assert entrypoint["worker"]["max_concurrent_workflow_tasks"] == 200
    assert entrypoint["worker"]["workflows"] == (GaiaRuntimeWorkflow, int)
    assert entrypoint["worker"]["activities"] == (str,)


def test_temporal_worker_entrypoint_checks_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "temporalio", None)
    with pytest.raises(TemporalRuntimeUnavailable):
        build_temporal_entrypoint_kwargs(
            execution=RuntimeExecutionSettings(provider="temporal"),
            workflows=(),
            activities=(),
        )


@pytest.mark.asyncio
async def test_build_temporal_worker_uses_real_sdk_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def connect(target: str, **kwargs: object) -> object:
        captured["connection"] = {"target": target, **kwargs}
        return object()

    class FakeWorker:
        def __init__(self, client: object, **kwargs: object) -> None:
            captured["client"] = client
            captured["worker"] = kwargs

    monkeypatch.setattr("gaia.runtime.temporal_worker.Client.connect", connect)
    monkeypatch.setattr("gaia.runtime.temporal_worker.Worker", FakeWorker)

    worker = await build_temporal_worker(execution=RuntimeExecutionSettings(provider="temporal"))

    assert isinstance(worker, FakeWorker)
    assert captured["connection"] == {
        "target": "127.0.0.1:7233",
        "namespace": "default",
        "tls": False,
    }
    assert captured["worker"]["workflows"] == (GaiaRuntimeWorkflow,)


@pytest.mark.asyncio
async def test_build_temporal_worker_propagates_runtime_tracing_interceptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    interceptor = object()

    async def connect(target: str, **kwargs: object) -> object:
        captured["connection"] = {"target": target, **kwargs}
        return object()

    class FakeWorker:
        def __init__(self, client: object, **kwargs: object) -> None:
            del client, kwargs

    monkeypatch.setattr("gaia.runtime.temporal_worker.Client.connect", connect)
    monkeypatch.setattr("gaia.runtime.temporal_worker.Worker", FakeWorker)

    await build_temporal_worker(
        execution=RuntimeExecutionSettings(provider="temporal"),
        runtime=TemporalRuntimeEngine(temporal_interceptors=(interceptor,)),
    )

    assert captured["connection"] == {
        "target": "127.0.0.1:7233",
        "namespace": "default",
        "tls": False,
        "interceptors": (interceptor,),
    }


def test_deployment_versioning_requires_both_name_and_build_id() -> None:
    """Half-configured versioning must fail loudly, not silently stay unpinned.

    A Worker with a deployment name but no build id is not "partly pinned" --
    it is unpinned, which is exactly the configuration in which a Workflow
    change strands Runs that are already in flight.
    """

    with pytest.raises(ValidationError):
        RuntimeExecutionSettings(deployment_name="gaia")
    with pytest.raises(ValidationError):
        RuntimeExecutionSettings(build_id="2026.07.30")


def test_worker_profile_has_no_deployment_config_by_default() -> None:
    profile = build_temporal_worker_profile(execution=RuntimeExecutionSettings(provider="temporal"))

    assert profile.deployment_config() is None


def test_worker_profile_pins_in_flight_runs_when_deployment_is_configured() -> None:
    profile = build_temporal_worker_profile(
        execution=RuntimeExecutionSettings(
            deployment_name="gaia-runtime",
            build_id="2026.07.30",
        )
    )

    config = profile.deployment_config()

    assert config is not None
    assert config.use_worker_versioning is True
    assert config.default_versioning_behavior is VersioningBehavior.PINNED
    assert config.version.deployment_name == "gaia-runtime"
    assert config.version.build_id == "2026.07.30"


@pytest.mark.asyncio
async def test_build_temporal_worker_passes_deployment_config_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def connect(target: str, **kwargs: object) -> object:
        return object()

    class FakeWorker:
        def __init__(self, client: object, **kwargs: object) -> None:
            captured["worker"] = kwargs

    monkeypatch.setattr("gaia.runtime.temporal_worker.Client.connect", connect)
    monkeypatch.setattr("gaia.runtime.temporal_worker.Worker", FakeWorker)

    await build_temporal_worker(
        execution=RuntimeExecutionSettings(
            deployment_name="gaia-runtime",
            build_id="2026.07.30",
        )
    )

    worker_kwargs = captured["worker"]
    assert isinstance(worker_kwargs, dict)
    assert worker_kwargs["deployment_config"].use_worker_versioning is True
