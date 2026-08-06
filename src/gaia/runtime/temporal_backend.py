"""Temporal Python SDK backend for the Gaia Runtime adapter."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, Protocol, cast

from temporalio.client import Client
from temporalio.common import (
    SearchAttributePair,
    TypedSearchAttributes,
    WorkflowIDConflictPolicy,
    WorkflowIDReusePolicy,
)
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from gaia.config.models import RuntimeExecutionSettings
from gaia.contracts.models import ErrorCode
from gaia.runtime.contracts import RuntimeConflict, RuntimeRunNotFound
from gaia.runtime.temporal_names import (
    GAIA_ORGANIZATION_SEARCH_ATTRIBUTE,
    GAIA_RUNTIME_WORKFLOW,
    GAIA_SCENARIO_SEARCH_ATTRIBUTE,
    GAIA_STATUS_SEARCH_ATTRIBUTE,
)
from gaia.runtime.temporal_runtime import TemporalRuntimeUnavailable


class TemporalWorkflowHandle(Protocol):
    async def query(self, query: str, arg: Any = ...) -> Any: ...

    async def signal(self, signal: str, arg: Any = ...) -> None: ...

    async def execute_update(self, update: str, arg: Any = ...) -> Any: ...


class TemporalClient(Protocol):
    async def start_workflow(
        self,
        workflow: str,
        arg: Any,
        **kwargs: Any,
    ) -> TemporalWorkflowHandle: ...

    def get_workflow_handle(self, workflow_id: str) -> TemporalWorkflowHandle: ...


TemporalClientFactory = Callable[[], Awaitable[TemporalClient]]


class TemporalClientBackend:
    """Map Runtime operations to a real Temporal Client and Workflow messages."""

    def __init__(
        self,
        execution: RuntimeExecutionSettings,
        *,
        client_factory: TemporalClientFactory | None = None,
        interceptors: tuple[Any, ...] = (),
    ) -> None:
        self._execution = execution
        self._client_factory = client_factory or self._connect
        self._client: TemporalClient | None = None
        self._interceptors = interceptors

    async def _connect(self) -> TemporalClient:
        kwargs: dict[str, Any] = {
            "namespace": self._execution.namespace,
            "tls": self._execution.tls_enabled,
        }
        if self._interceptors:
            kwargs["interceptors"] = self._interceptors
        return cast(
            TemporalClient,
            await Client.connect(self._execution.server_address, **kwargs),
        )

    async def _get_client(self) -> TemporalClient:
        if self._client is None:
            self._client = await self._client_factory()
        return self._client

    @staticmethod
    def _workflow_id(payload: dict[str, object]) -> str:
        request = payload["request"]
        if not isinstance(request, dict):
            raise TemporalRuntimeUnavailable("create: request payload must be a dict")
        user = request.get("user")
        organization = user.get("organization") if isinstance(user, dict) else None
        scope = f"{organization}:{payload['idempotency_key']}"
        digest = hashlib.sha256(scope.encode()).hexdigest()[:32]
        return f"gaia-run-{digest}"

    @staticmethod
    async def _snapshot(handle: TemporalWorkflowHandle) -> dict[str, object]:
        value = await handle.query("snapshot")
        if not isinstance(value, dict):
            raise TemporalRuntimeUnavailable("Temporal snapshot query must return a dict")
        return value

    async def _create(self, payload: dict[str, object]) -> dict[str, object]:
        if "version_bundle" not in payload:
            raise TemporalRuntimeUnavailable(
                "create: Gaia admission and version resolution must run before Temporal start"
            )
        client = await self._get_client()
        workflow_id = self._workflow_id(payload)
        workflow_payload = {
            **payload,
            "run_id": workflow_id,
            "activity_timeout_seconds": self._execution.task_timeout_seconds,
        }
        request = cast(dict[str, object], payload["request"])
        user = cast(dict[str, object], request["user"])
        try:
            handle = await client.start_workflow(
                GAIA_RUNTIME_WORKFLOW,
                workflow_payload,
                id=workflow_id,
                task_queue=self._execution.task_queue,
                task_timeout=timedelta(seconds=self._execution.task_timeout_seconds),
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                search_attributes=TypedSearchAttributes(
                    [
                        SearchAttributePair(
                            GAIA_ORGANIZATION_SEARCH_ATTRIBUTE,
                            str(user["organization"]),
                        ),
                        SearchAttributePair(
                            GAIA_SCENARIO_SEARCH_ATTRIBUTE,
                            str(request["scenario_id"]),
                        ),
                        SearchAttributePair(
                            GAIA_STATUS_SEARCH_ATTRIBUTE,
                            "received",
                        ),
                    ]
                ),
            )
        except WorkflowAlreadyStartedError:
            handle = client.get_workflow_handle(workflow_id)
        fingerprint = await handle.query("request_fingerprint")
        if fingerprint != payload["request_fingerprint"]:
            raise RuntimeConflict(ErrorCode.IDEMPOTENCY_CONFLICT.value)
        return await self._snapshot(handle)

    async def __call__(self, operation: str, payload: dict[str, object]) -> object:
        if operation == "create":
            return await self._create(payload)
        client = await self._get_client()
        if operation in {
            "inspect",
            "events_after",
            "cancel",
            "decide",
            "get_gate",
        }:
            run_id_value: object
            if operation in {"decide", "get_gate"}:
                gate_id = payload.get("gate_id")
                if not isinstance(gate_id, str) or ":gate:" not in gate_id:
                    raise TemporalRuntimeUnavailable(
                        f"{operation}: Temporal gate_id is invalid"
                    )
                run_id_value = gate_id.split(":gate:", 1)[0]
            else:
                run_id_value = payload.get("run_id")
            if not isinstance(run_id_value, str):
                raise TemporalRuntimeUnavailable(f"{operation}: run_id is required")
            handle = client.get_workflow_handle(run_id_value)
            try:
                if operation == "inspect":
                    return await self._snapshot(handle)
                if operation == "events_after":
                    return await handle.query(
                        "events_after", payload.get("sequence", 0)
                    )
                if operation == "get_gate":
                    return await handle.query("gate", payload["gate_id"])
                if operation == "decide":
                    return await handle.execute_update("decide", payload)
                await handle.signal("cancel", payload)
                return await self._snapshot(handle)
            except RPCError as error:
                # Temporal returns NOT_FOUND immediately for a Workflow it has
                # already deleted -- the normal state of any Run older than the
                # namespace retention window. That is a different fact from the
                # server being unreachable, and only this one may be answered
                # from the audit projection instead.
                if error.status is not RPCStatusCode.NOT_FOUND:
                    raise
                raise RuntimeRunNotFound(run_id_value) from error
        raise TemporalRuntimeUnavailable(
            f"Temporal operation {operation!r} is not mapped in the first replacement slice"
        )
