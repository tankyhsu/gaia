"""Temporal worker/bootstrap primitives used for the runtime migration path.

This module intentionally keeps runtime migration concrete but narrowly scoped:
it turns Gaia runtime execution config into a deterministic Temporal worker
profile and centralizes dependency/connection checks for the first replacement
batch. Actual workflow bodies are still introduced in later phases.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from temporalio.client import Client
from temporalio.common import VersioningBehavior, WorkerDeploymentVersion
from temporalio.worker import Worker, WorkerDeploymentConfig
from temporalio.worker.workflow_sandbox import (
    SandboxedWorkflowRunner,
    SandboxRestrictions,
)

from gaia.config.models import RuntimeExecutionSettings
from gaia.runtime.temporal_runtime import TemporalRuntimeEngine, TemporalRuntimeUnavailable
from gaia.runtime.temporal_workflow import GaiaRuntimeWorkflow


class TemporalWorkerProfileError(ValueError):
    """Raised when Temporal execution config cannot be interpreted."""


def _parse_server_address(address: str) -> tuple[str, int]:
    raw = address.strip()
    if not raw:
        raise TemporalWorkerProfileError("runtime.execution.server_address cannot be empty")

    # Accept the common host-only shorthand and append default Temporal port.
    if ":" not in raw:
        return raw, 7233

    # Keep support for bracketed IPv6 host definitions: [::1]:7233.
    if raw.startswith("[") and "]" in raw and raw.count("]") == 1:
        host = raw[1 : raw.index("]")]
        suffix = raw[raw.index("]") + 1 :]
        if not suffix:
            return host, 7233
        if not suffix.startswith(":"):
            raise TemporalWorkerProfileError(f"invalid server address {address!r}")
        try:
            return host, int(suffix[1:])
        except ValueError as error:
            raise TemporalWorkerProfileError(
                f"invalid port in server address {address!r}"
            ) from error

    parts = raw.rsplit(":", 1)
    if len(parts) != 2:
        raise TemporalWorkerProfileError(f"invalid server address {address!r}")
    host, port_text = parts
    if not host:
        raise TemporalWorkerProfileError(f"invalid server address {address!r}")
    try:
        return host, int(port_text)
    except ValueError as error:
        raise TemporalWorkerProfileError(
            f"invalid port in server address {address!r}"
        ) from error


@dataclass(frozen=True)
class TemporalWorkerProfile:
    """Concrete connection + execution profile for the migration worker."""

    namespace: str
    task_queue: str
    host: str
    port: int
    tls_enabled: bool
    task_timeout_seconds: int
    max_concurrent_workflows: int
    server_address: str
    deployment_name: str | None = None
    build_id: str | None = None

    @classmethod
    def from_execution_settings(
        cls, settings: RuntimeExecutionSettings
    ) -> TemporalWorkerProfile:
        host, port = _parse_server_address(settings.server_address)
        return cls(
            namespace=settings.namespace,
            task_queue=settings.task_queue,
            host=host,
            port=port,
            tls_enabled=settings.tls_enabled,
            task_timeout_seconds=settings.task_timeout_seconds,
            max_concurrent_workflows=settings.max_concurrent_workflows,
            server_address=settings.server_address,
            deployment_name=settings.deployment_name,
            build_id=settings.build_id,
        )

    def deployment_config(self) -> WorkerDeploymentConfig | None:
        """Pin in-flight Runs to the build they started on, when configured.

        `PINNED` is set here as the deployment default rather than on
        `GaiaRuntimeWorkflow` itself: declaring it on the Workflow class makes a
        Worker without a deployment configuration stop accepting Workflow tasks
        at all, so the safe-by-default path would become the broken one.
        """

        if self.deployment_name is None or self.build_id is None:
            return None
        return WorkerDeploymentConfig(
            version=WorkerDeploymentVersion(
                deployment_name=self.deployment_name,
                build_id=self.build_id,
            ),
            use_worker_versioning=True,
            default_versioning_behavior=VersioningBehavior.PINNED,
        )

    def client_connection_kwargs(self) -> dict[str, object]:
        return {
            "target": self.server_address,
            "namespace": self.namespace,
            "tls": self.tls_enabled,
        }

    def worker_kwargs(self) -> dict[str, object]:
        return {
            "task_queue": self.task_queue,
            "max_concurrent_workflow_tasks": self.max_concurrent_workflows,
        }


def ensure_temporal_runtime_available() -> None:
    """Import-time check for optional temporal dependencies.

    We do not eagerly import `temporalio` from module import scope so importing
    Gaia's public Python API and testing utilities do not require a running Temporal service.
    """

    try:
        import_module("temporalio")
    except ModuleNotFoundError as error:
        raise TemporalRuntimeUnavailable(
            "runtime.execution.provider=temporal is selected but python package "
            "`temporalio` is not installed. Install `gaia-framework[temporal]`."
        ) from error


def gaia_workflow_runner() -> SandboxedWorkflowRunner:
    """Keep Gaia imports outside the sandbox while sandboxing Workflow execution.

    Importing any ``gaia.*`` module executes Gaia's package initializer, which
    exposes FastAPI-facing public API symbols that Temporal cannot safely re-import
    inside the Workflow sandbox. Passthrough reuses the already-loaded,
    immutable module objects; Temporal still validates deterministic calls made
    by the Workflow itself.
    """

    return SandboxedWorkflowRunner(
        restrictions=SandboxRestrictions.default.with_passthrough_modules("gaia")
    )


def build_temporal_worker_profile(
    *, execution: RuntimeExecutionSettings
) -> TemporalWorkerProfile:
    """Return a migration-ready Temporal execution profile."""

    return TemporalWorkerProfile.from_execution_settings(execution)


def build_temporal_entrypoint_kwargs(
    *,
    execution: RuntimeExecutionSettings,
    workflows: tuple[type[Any], ...],
    activities: tuple[Any, ...],
) -> dict[str, dict[str, object]]:
    """Build a deterministic, testable contract for Temporal bootstrap wiring."""

    ensure_temporal_runtime_available()
    profile = build_temporal_worker_profile(execution=execution)
    return {
        "connection": profile.client_connection_kwargs(),
        "worker": {
            **profile.worker_kwargs(),
            "workflows": (GaiaRuntimeWorkflow, *workflows),
            "activities": tuple(activities),
        },
    }


async def build_temporal_worker(
    *,
    execution: RuntimeExecutionSettings,
    runtime: TemporalRuntimeEngine | None = None,
    activities: tuple[Any, ...] = (),
    workflows: tuple[type[Any], ...] = (),
) -> Worker:
    """Connect and construct the real Temporal Worker for a Gaia application."""

    ensure_temporal_runtime_available()
    profile = build_temporal_worker_profile(execution=execution)
    runtime_activities = () if runtime is None else runtime.activity_handlers()
    connection_kwargs: dict[str, Any] = {
        "namespace": profile.namespace,
        "tls": profile.tls_enabled,
    }
    if runtime is not None and runtime.temporal_interceptors:
        connection_kwargs["interceptors"] = runtime.temporal_interceptors
    client = await Client.connect(profile.server_address, **connection_kwargs)
    worker_kwargs: dict[str, Any] = {}
    deployment_config = profile.deployment_config()
    if deployment_config is not None:
        worker_kwargs["deployment_config"] = deployment_config
    return Worker(
        client,
        task_queue=profile.task_queue,
        max_concurrent_workflow_tasks=profile.max_concurrent_workflows,
        workflow_runner=gaia_workflow_runner(),
        workflows=(GaiaRuntimeWorkflow, *workflows),
        activities=(*runtime_activities, *activities),
        **worker_kwargs,
    )


async def run_temporal_worker(
    *,
    execution: RuntimeExecutionSettings,
    runtime: TemporalRuntimeEngine | None = None,
    activities: tuple[Any, ...] = (),
    workflows: tuple[type[Any], ...] = (),
) -> None:
    """Run the Gaia Temporal Worker until shutdown."""

    worker = await build_temporal_worker(
        execution=execution,
        runtime=runtime,
        activities=activities,
        workflows=workflows,
    )
    await worker.run()
