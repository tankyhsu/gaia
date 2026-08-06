"""Narrow Runtime SPI captures for API boundary tests.

These doubles do not execute scenarios or model durable behavior. Temporal
integration tests own execution semantics; API tests only need to observe the
request that crossed the Runtime boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime

from gaia.api.app import ApiDependencies
from gaia.contracts.models import (
    RunRequest,
    RunSnapshot,
    RunStatus,
    VersionBundle,
)
from gaia.runtime.temporal_runtime import TemporalRuntimeEngine


class CreateCaptureRuntime(TemporalRuntimeEngine):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[RunRequest] = []
        self.idempotency_keys: list[str] = []

    async def create(
        self,
        request: RunRequest,
        idempotency_key: str,
    ) -> RunSnapshot:
        self.requests.append(request)
        self.idempotency_keys.append(idempotency_key)
        now = datetime.now(UTC)
        return RunSnapshot(
            run_id=f"capture-run-{len(self.requests)}",
            scenario_id=request.scenario_id,
            mode=request.mode,
            status=RunStatus.RUNNING,
            user=request.user,
            version_bundle=VersionBundle(
                policy="capture:1",
                workflow="capture:1",
                rules="capture:1",
                prompt="capture:1",
                model_profile="capture:1",
                toolset="capture:1",
                context_profile="capture:1",
            ),
            created_at=now,
            updated_at=now,
        )


def capture_api_dependencies(runtime: CreateCaptureRuntime) -> ApiDependencies:
    def runtime_factory(factory: object, database_url: str) -> CreateCaptureRuntime:
        del factory, database_url
        return runtime

    return ApiDependencies(runtime_factory=runtime_factory)
