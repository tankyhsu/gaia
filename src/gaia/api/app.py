"""FastAPI boundary shared by Gaia applications."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gaia.api.actuator import create_actuator_router
from gaia.application import GaiaApplication
from gaia.config import GaiaApplicationConfig, resolve_secret
from gaia.contracts.models import (
    CancelRequest,
    ErrorCode,
    HealthResponse,
    HumanGate,
    HumanGateDecisionRequest,
    ModelHealth,
    ReplayRequest,
    ReplaySnapshot,
    RunEvent,
    RunRequest,
    RunSnapshot,
)
from gaia.diagnostics.bundle import DiagnosticExporter
from gaia.diagnostics.error_catalog import operational_error
from gaia.evals.replay import ReplayRunner
from gaia.guardrails import RunGuardrailObservability, SqlAlchemyGuardrailDecisionStore
from gaia.observability.models import RunModelObservability
from gaia.observability.store import SqlAlchemyModelInvocationStore
from gaia.persistence.database import session_factory_resource
from gaia.persistence.urls import database_backend
from gaia.runtime.dependencies import VersionResolutionError
from gaia.runtime.persistent_engine import (
    PersistentRuntimeEngine,
    RuntimeConflict,
    RuntimePermissionDenied,
)
from gaia.sdk.prompt import PromptProvider
from gaia.sdk.scenario import ScenarioHandler, get_scenario_spec
from gaia.sdk.tool import ToolHandler

from .sse import stream_run_events

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApiDependencies:
    """Factories supplied by a Gaia application composition root."""

    runtime_factory: Callable[[async_sessionmaker[AsyncSession], str], PersistentRuntimeEngine]
    replay_factory: Callable[[async_sessionmaker[AsyncSession]], ReplayRunner] | None = None
    model_health: Callable[[], Awaitable[ModelHealth]] | None = None
    lifespan: Callable[[], AbstractAsyncContextManager[Any]] | None = None

    @classmethod
    def from_scenarios(
        cls,
        config: GaiaApplicationConfig,
        *handlers: ScenarioHandler,
        write_tools: Iterable[ToolHandler] = (),
        prompt_provider: PromptProvider | Callable[[], PromptProvider] | None = None,
    ) -> ApiDependencies:
        """Build the minimal durable Runtime for decorated function scenarios."""

        from gaia.runtime import (
            FunctionScenarioRunner,
            PromptRunVersionResolver,
            RuntimeDependencies,
            WriteToolRegistry,
            function_write_tool,
        )

        specs = tuple(get_scenario_spec(handler) for handler in handlers)
        tool_registrations = tuple(function_write_tool(handler) for handler in write_tools)
        scenario_ids = [spec.scenario_id for spec in specs]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("duplicate scenario_id in API dependencies")
        prompt_refs = {
            spec.scenario_id: spec.prompt_ref for spec in specs if spec.prompt_ref is not None
        }
        if prompt_refs and prompt_provider is None:
            raise ValueError("scenario PromptRef requires prompt_provider")

        def runtime_factory(
            factory: async_sessionmaker[AsyncSession],
            _database_url: str,
        ) -> PersistentRuntimeEngine:
            runtime_prompt_provider = (
                prompt_provider()
                if callable(prompt_provider) and not isinstance(prompt_provider, PromptProvider)
                else prompt_provider
            )
            version_resolver = (
                PromptRunVersionResolver(runtime_prompt_provider, prompt_refs)
                if runtime_prompt_provider is not None
                else None
            )
            dependencies_kwargs: dict[str, Any] = {}
            if version_resolver is not None:
                dependencies_kwargs["version_resolver"] = version_resolver
            return PersistentRuntimeEngine(
                factory,
                RuntimeDependencies(
                    runners={
                        spec.scenario_id: FunctionScenarioRunner(spec.handler, spec)
                        for spec in specs
                    },
                    write_tools=WriteToolRegistry(tool_registrations),
                    environment=config.runtime.environment,
                    environment_write_mode=config.runtime.effective_write_mode(),
                    **dependencies_kwargs,
                ),
            )

        return cls(runtime_factory=runtime_factory)


class RuntimeUnavailable(RuntimeError):
    """Raised when an application has not installed runtime dependencies."""


def create_app(
    database_url: str | None = None,
    api_key: str | None = None,
    *,
    dependencies: ApiDependencies | None = None,
    gaia_application: GaiaApplication | None = None,
    sse_poll_interval_seconds: float | None = None,
    sse_heartbeat_seconds: float | None = None,
    enable_devtools: bool | None = None,
) -> FastAPI:
    managed_application = gaia_application or GaiaApplication(GaiaApplicationConfig())
    explicit_database = database_url or os.environ.get("GAIA_DATABASE_URL")
    configured_database = explicit_database or resolve_secret(
        managed_application.config.runtime.database_url
    )
    operational_store = managed_application.config.stores.operational
    if (
        explicit_database is None
        and database_backend(configured_database) != operational_store.provider
    ):
        raise ValueError("OPERATIONAL_STORE_PROVIDER_MISMATCH")
    configured_key = api_key
    if configured_key is None:
        configured_key = os.environ.get("GAIA_API_KEY", "gaia-dev-key")
    configured_sse_poll = _duration_setting(
        sse_poll_interval_seconds, "GAIA_SSE_POLL_INTERVAL_SECONDS", 0.25
    )
    configured_sse_heartbeat = _duration_setting(
        sse_heartbeat_seconds, "GAIA_SSE_HEARTBEAT_SECONDS", 15.0
    )
    configured_devtools = (
        _boolean_setting("GAIA_DEVTOOLS_ENABLED", False)
        if enable_devtools is None
        else enable_devtools
    )
    configured_project_root = Path(os.environ.get("GAIA_PROJECT_ROOT", ".")).resolve()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            factory = await stack.enter_async_context(
                session_factory_resource(
                    configured_database,
                    pool_size=operational_store.pool_size,
                    max_overflow=operational_store.max_overflow,
                    pool_timeout_seconds=operational_store.pool_timeout_seconds,
                    pool_recycle_seconds=operational_store.pool_recycle_seconds,
                    auto_create=operational_store.auto_create,
                )
            )
            app.state.gaia_application = managed_application
            app.state.session_factory = factory
            await stack.enter_async_context(managed_application.lifespan())
            if dependencies is not None and dependencies.lifespan is not None:
                await stack.enter_async_context(dependencies.lifespan())
            runtime_engine = (
                None
                if dependencies is None
                else dependencies.runtime_factory(factory, configured_database)
            )
            app.state.runtime = runtime_engine
            app.state.startup_recovery_runs = (
                [] if runtime_engine is None else await runtime_engine.startup_recover()
            )
            app.state.replays = (
                None
                if dependencies is None or dependencies.replay_factory is None
                else dependencies.replay_factory(factory)
            )
            app.state.diagnostics = DiagnosticExporter(factory)
            app.state.model_invocations = SqlAlchemyModelInvocationStore(factory)
            app.state.guardrail_decisions = SqlAlchemyGuardrailDecisionStore(factory)
            yield

    app = FastAPI(title="Gaia Application Framework API", version="0.1.0", lifespan=lifespan)

    def runtime(request: Request) -> PersistentRuntimeEngine:
        value = request.app.state.runtime
        if value is None:
            raise RuntimeUnavailable("runtime components are not configured")
        return cast(PersistentRuntimeEngine, value)

    def trace_id(request: Request) -> str:
        return request.headers.get("X-Trace-Id") or str(uuid4())

    def replays(request: Request) -> ReplayRunner:
        value = request.app.state.replays
        if value is None:
            raise RuntimeUnavailable("evaluation components are not configured")
        return cast(ReplayRunner, value)

    def diagnostics(request: Request) -> DiagnosticExporter:
        return cast(DiagnosticExporter, request.app.state.diagnostics)

    def model_invocations(request: Request) -> SqlAlchemyModelInvocationStore:
        return cast(SqlAlchemyModelInvocationStore, request.app.state.model_invocations)

    def guardrail_decisions(request: Request) -> SqlAlchemyGuardrailDecisionStore:
        return cast(
            SqlAlchemyGuardrailDecisionStore,
            request.app.state.guardrail_decisions,
        )

    def error_response(
        request: Request,
        status_code: int,
        code: ErrorCode | str,
        *,
        details: dict[str, Any] | None = None,
    ) -> JSONResponse:
        value = code.value if isinstance(code, ErrorCode) else code
        body = operational_error(
            value,
            trace_id=trace_id(request),
            details=details,
        )
        log = logger.error if status_code >= 500 else logger.warning
        log(
            "gaia_request_error code=%s category=%s retryable=%s trace_id=%s message=%s",
            value,
            body.category,
            body.retryable,
            body.trace_id,
            body.message,
        )
        return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))

    def authorize(request: Request) -> JSONResponse | None:
        if request.headers.get("X-Gaia-Api-Key") != configured_key:
            return error_response(request, 401, ErrorCode.UNAUTHORIZED)
        return None

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return error_response(
            request,
            422,
            ErrorCode.INVALID_REQUEST,
            details={"errors": error.errors()},
        )

    @app.exception_handler(RuntimeUnavailable)
    async def runtime_unavailable(request: Request, error: RuntimeUnavailable) -> JSONResponse:
        return error_response(
            request,
            503,
            "RUNTIME_UNAVAILABLE",
            details={"reason": str(error)},
        )

    app.include_router(
        create_actuator_router(
            authorize,
            devtools_enabled=configured_devtools,
        )
    )
    if configured_devtools:
        from gaia.api.devtools_project import create_project_devtools_router
        from gaia.api.devtools_prompts import create_prompt_devtools_router

        app.include_router(create_prompt_devtools_router(authorize, managed_application))
        app.include_router(create_project_devtools_router(authorize, configured_project_root))

    @app.get("/health/live", response_model=HealthResponse)
    async def live() -> HealthResponse:
        return HealthResponse(status="ok", checks={"process": "ok"})

    @app.get("/health/ready", response_model=HealthResponse)
    async def ready(request: Request, response: Response) -> HealthResponse:
        recovered = cast(list[str], request.app.state.startup_recovery_runs)
        model_status = "not_configured"
        if dependencies is not None and dependencies.model_health is not None:
            try:
                model = await dependencies.model_health()
                model_status = "ok" if model.healthy else "down"
            except Exception:
                logger.exception("gaia_readiness_model_health_failed")
                model_status = "down"
        if model_status == "down":
            response.status_code = 503
        return HealthResponse(
            status="ok" if model_status != "down" else "unavailable",
            checks={
                "database": "ok",
                "application": managed_application.state.value,
                "runtime": "ok" if request.app.state.runtime is not None else "not_configured",
                "model": model_status,
                "environment": managed_application.config.runtime.environment.value,
                "write_mode": managed_application.config.runtime.effective_write_mode().value,
                "startup_recovery_runs": str(len(recovered)),
            },
        )

    @app.post("/v1/runs", status_code=201, response_model=RunSnapshot)
    async def create_run(
        request: Request,
        body: RunRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ) -> RunSnapshot | JSONResponse:
        if unauthorized := authorize(request):
            return unauthorized
        try:
            return await runtime(request).create(body, idempotency_key)
        except RuntimePermissionDenied as error:
            return error_response(request, 403, str(error))
        except RuntimeConflict as error:
            return error_response(request, 409, str(error))
        except VersionResolutionError as error:
            return error_response(
                request,
                503 if error.retryable else 409,
                error.code,
            )

    @app.get("/v1/runs/{run_id}", response_model=RunSnapshot)
    async def get_run(request: Request, run_id: str) -> RunSnapshot | JSONResponse:
        if unauthorized := authorize(request):
            return unauthorized
        try:
            return await runtime(request).inspect(run_id)
        except KeyError:
            return error_response(request, 404, "RUN_NOT_FOUND")

    @app.get(
        "/v1/runs/{run_id}/model-invocations",
        response_model=RunModelObservability,
    )
    async def list_model_invocations(
        request: Request,
        run_id: str,
    ) -> RunModelObservability | JSONResponse:
        if unauthorized := authorize(request):
            return unauthorized
        try:
            await runtime(request).inspect(run_id)
        except KeyError:
            return error_response(request, 404, "RUN_NOT_FOUND")
        return await model_invocations(request).for_run(run_id)

    @app.get(
        "/v1/runs/{run_id}/guardrail-decisions",
        response_model=RunGuardrailObservability,
    )
    async def list_guardrail_decisions(
        request: Request,
        run_id: str,
    ) -> RunGuardrailObservability | JSONResponse:
        if unauthorized := authorize(request):
            return unauthorized
        try:
            await runtime(request).inspect(run_id)
        except KeyError:
            return error_response(request, 404, "RUN_NOT_FOUND")
        return await guardrail_decisions(request).for_run(run_id)

    @app.post("/v1/runs/{run_id}/cancel", response_model=RunSnapshot)
    async def cancel_run(
        request: Request, run_id: str, body: CancelRequest
    ) -> RunSnapshot | JSONResponse:
        if unauthorized := authorize(request):
            return unauthorized
        try:
            return await runtime(request).cancel(run_id, body.reason)
        except KeyError:
            return error_response(request, 404, "RUN_NOT_FOUND")
        except RuntimeConflict as error:
            return error_response(request, 409, str(error))

    @app.get("/v1/runs/{run_id}/events", response_model=list[RunEvent])
    async def list_events(
        request: Request, run_id: str, after: int = 0
    ) -> list[RunEvent] | JSONResponse:
        if unauthorized := authorize(request):
            return unauthorized
        try:
            return await runtime(request).events_after(run_id, after)
        except KeyError:
            return error_response(request, 404, "RUN_NOT_FOUND")

    @app.get("/v1/runs/{run_id}/events/stream", response_model=None)
    async def stream_events(
        request: Request,
        run_id: str,
        last_event_id: int = Header(default=0, alias="Last-Event-ID", ge=0),
    ) -> StreamingResponse | JSONResponse:
        if unauthorized := authorize(request):
            return unauthorized
        try:
            await runtime(request).inspect(run_id)
        except KeyError:
            return error_response(request, 404, "RUN_NOT_FOUND")

        async def generate() -> AsyncIterator[str]:
            async for frame in stream_run_events(
                request,
                runtime(request),
                run_id,
                last_event_id=last_event_id,
                poll_interval_seconds=configured_sse_poll,
                heartbeat_seconds=configured_sse_heartbeat,
            ):
                yield frame

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/v1/human-gates/{gate_id}", response_model=HumanGate)
    async def get_gate(request: Request, gate_id: str) -> HumanGate | JSONResponse:
        if unauthorized := authorize(request):
            return unauthorized
        try:
            return await runtime(request).get_gate(gate_id)
        except KeyError:
            return error_response(request, 404, "GATE_NOT_FOUND")

    @app.post("/v1/human-gates/{gate_id}/decision", response_model=RunSnapshot)
    async def decide(
        request: Request, gate_id: str, body: HumanGateDecisionRequest
    ) -> RunSnapshot | JSONResponse:
        if unauthorized := authorize(request):
            return unauthorized
        try:
            return await runtime(request).decide(gate_id, body)
        except KeyError:
            return error_response(request, 404, "GATE_NOT_FOUND")
        except RuntimePermissionDenied as error:
            return error_response(request, 403, str(error))
        except RuntimeConflict as error:
            return error_response(request, 409, str(error))

    @app.get("/v1/model-profiles/current/health", response_model=ModelHealth)
    async def model_health(request: Request) -> ModelHealth | JSONResponse:
        if unauthorized := authorize(request):
            return unauthorized
        if dependencies is None or dependencies.model_health is None:
            return error_response(request, 503, ErrorCode.MODEL_UNAVAILABLE)
        return await dependencies.model_health()

    @app.post("/v1/evals/replays", status_code=201, response_model=ReplaySnapshot)
    async def create_replay(request: Request, body: ReplayRequest) -> ReplaySnapshot | JSONResponse:
        if unauthorized := authorize(request):
            return unauthorized
        try:
            return await replays(request).run(body)
        except ValueError as error:
            return error_response(request, 422, str(error))

    @app.get("/v1/evals/replays/{replay_id}", response_model=ReplaySnapshot)
    async def get_replay(request: Request, replay_id: str) -> ReplaySnapshot | JSONResponse:
        if unauthorized := authorize(request):
            return unauthorized
        try:
            return await replays(request).get(replay_id)
        except KeyError:
            return error_response(request, 404, "REPLAY_NOT_FOUND")

    @app.get("/v1/diagnostics/runs/{run_id}/bundle", response_model=None)
    async def diagnostic_bundle(request: Request, run_id: str) -> dict[str, Any] | JSONResponse:
        if unauthorized := authorize(request):
            return unauthorized
        try:
            return await diagnostics(request).export(run_id)
        except KeyError:
            return error_response(request, 404, "RUN_NOT_FOUND")

    return app


def _duration_setting(explicit: float | None, environment_name: str, default: float) -> float:
    value = explicit
    if value is None:
        value = float(os.environ.get(environment_name, str(default)))
    if value <= 0:
        raise ValueError(f"{environment_name} must be positive")
    return value


def _boolean_setting(environment_name: str, default: bool) -> bool:
    raw = os.environ.get(environment_name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{environment_name} must be a boolean")
