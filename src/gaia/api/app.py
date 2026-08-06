"""FastAPI boundary shared by Gaia applications."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gaia._authoring.scenario import ScenarioHandler
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
    RunPage,
    RunRequest,
    RunSnapshot,
    RunStatus,
    UserIdentity,
)
from gaia.diagnostics.bundle import DiagnosticExporter
from gaia.diagnostics.error_catalog import operational_error
from gaia.evals.replay import ReplayRunner
from gaia.guardrails import (
    RunGuardrailObservability,
    SqlAlchemyGuardrailDecisionStore,
)
from gaia.integrations.api_key import ApiKeyAuthnProvider
from gaia.observability.models import RunModelObservability, RunToolObservability
from gaia.observability.store import SqlAlchemyModelInvocationStore
from gaia.observability.tool_store import SqlAlchemyToolInvocationStore
from gaia.persistence.database import session_factory_resource
from gaia.persistence.urls import database_backend
from gaia.runtime.assembly import RuntimeAssembler, _normalize_guardrails
from gaia.runtime.contracts import (
    RUN_LIST_DEFAULT_LIMIT,
    RUN_LIST_MAX_LIMIT,
    InvalidRunCursor,
    RuntimeConflict,
    RuntimeEngine,
    RuntimePermissionDenied,
)
from gaia.runtime.dependencies import VersionResolutionError
from gaia.spi.auth import AuthenticationError, AuthnProvider
from gaia.spi.guardrail import ContentGuardrail, GuardrailStage
from gaia.spi.model import ModelProvider
from gaia.spi.prompt import PromptProvider
from gaia.spi.rag import Retriever
from gaia.spi.tool import ToolHandler

from .sse import stream_run_events

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApiDependencies:
    """Factories supplied by a Gaia application composition root."""

    runtime_factory: Callable[[async_sessionmaker[AsyncSession], str], RuntimeEngine]
    replay_factory: Callable[[async_sessionmaker[AsyncSession]], ReplayRunner] | None = None
    model_health: Callable[[], Awaitable[ModelHealth]] | None = None
    lifespan: Callable[[], AbstractAsyncContextManager[Any]] | None = None

    @classmethod
    def from_scenarios(
        cls,
        config: GaiaApplicationConfig,
        *handlers: ScenarioHandler,
        tools: Iterable[ToolHandler] = (),
        write_tools: Iterable[ToolHandler] = (),
        model_provider: ModelProvider | None = None,
        retriever: Retriever | Callable[[], Retriever] | None = None,
        guardrails: Mapping[GuardrailStage, Iterable[ContentGuardrail]] | None = None,
        tool_guardrails: Iterable[ContentGuardrail] = (),
        prompt_provider: PromptProvider | Callable[[], PromptProvider] | None = None,
        handoff_handlers: Mapping[str, ScenarioHandler] | None = None,
        continuation_handlers: Mapping[str, ScenarioHandler] | None = None,
        allowed_handoffs: Mapping[str, tuple[str, ...]] | None = None,
        max_handoffs: int = 4,
        output_correction_attempts: int = 0,
    ) -> ApiDependencies:
        """Build the minimal durable Runtime for decorated function scenarios."""

        tool_handlers = (*tools, *write_tools)
        stage_guardrails = _normalize_guardrails(guardrails, tool_guardrails)
        assembler = RuntimeAssembler(
            config=config,
            scenario_handlers=tuple(handlers),
            tool_handlers=tool_handlers,
            model_provider=model_provider,
            retriever=retriever,
            guardrails=stage_guardrails,
            prompt_provider=prompt_provider,
            handoff_handlers=handoff_handlers,
            continuation_handlers=continuation_handlers,
            allowed_handoffs=allowed_handoffs,
            max_handoffs=max_handoffs,
            output_correction_attempts=output_correction_attempts,
        )
        return cls(runtime_factory=assembler.create_engine)


class RuntimeUnavailable(RuntimeError):
    """Raised when an application has not installed runtime dependencies."""


def _optional_component(application: GaiaApplication, component_id: str) -> RuntimeAssembler | None:
    """Look up `component_id` on `application`, treating "not started", "not found", and
    "wrong type" as absent rather than errors.

    `GaiaApplication.get_component` raises `RuntimeError("APPLICATION_NOT_STARTED")` before
    the application has entered its lifespan, `KeyError("COMPONENT_NOT_FOUND:<id>")` when
    no such component was registered (e.g. no `scenario-runtime` starter is configured), and
    (with `expected=RuntimeAssembler`) `TypeError("COMPONENT_TYPE_MISMATCH:...")` when a
    component is registered under this id but is not actually a `RuntimeAssembler`; all three
    just mean `create_app` has nothing usable to fall back to.
    """

    try:
        return cast(
            RuntimeAssembler,
            application.get_component(component_id, expected=RuntimeAssembler),
        )
    except (RuntimeError, KeyError, TypeError):
        return None


def create_app(
    database_url: str | None = None,
    api_key: str | None = None,
    *,
    dependencies: ApiDependencies | None = None,
    gaia_application: GaiaApplication | None = None,
    sse_poll_interval_seconds: float | None = None,
    sse_heartbeat_seconds: float | None = None,
    enable_devtools: bool | None = None,
    authn: AuthnProvider | None = None,
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
    # Default is byte-identical to the pre-authn-SPI behaviour: a valid
    # `X-Gaia-Api-Key` authenticates the calling service with no end-user
    # identity, so `RunRequest.user` is used exactly as submitted. See
    # `gaia.integrations.ApiKeyAuthnProvider` for the trust boundary this implies.
    #
    # An explicit `authn=` always wins. Absent that, `gaia.yaml`'s
    # `authn.provider: oidc` (see `gaia.config.models.AuthnSettings`, task F2)
    # builds a `JwtAuthnProvider` from config; `authn.provider` defaults to
    # `"disabled"`, so an application that configures nothing gets exactly
    # today's `ApiKeyAuthnProvider` default -- unchanged.
    active_authn: AuthnProvider
    if authn is not None:
        active_authn = authn
    elif managed_application.config.authn.provider == "oidc":
        from gaia.integrations.oidc import JwtAuthnProvider

        active_authn = JwtAuthnProvider.from_settings(managed_application.config.authn)
    else:
        active_authn = ApiKeyAuthnProvider(configured_key)
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
            runtime_engine: RuntimeEngine | None
            if dependencies is not None:
                # Explicitly supplied dependencies always win over the component graph,
                # so existing applications keep their current behaviour unchanged.
                runtime_engine = dependencies.runtime_factory(factory, configured_database)
            else:
                assembler = _optional_component(managed_application, "runtime-assembler")
                runtime_engine = (
                    None
                    if assembler is None
                    else assembler.create_engine(factory, configured_database)
                )
            app.state.runtime = runtime_engine
            app.state.replays = (
                None
                if dependencies is None or dependencies.replay_factory is None
                else dependencies.replay_factory(factory)
            )
            app.state.diagnostics = (
                None if runtime_engine is None else DiagnosticExporter(runtime_engine)
            )
            app.state.model_invocations = SqlAlchemyModelInvocationStore(factory)
            app.state.tool_invocations = SqlAlchemyToolInvocationStore(factory)
            app.state.guardrail_decisions = SqlAlchemyGuardrailDecisionStore(factory)
            yield

    app = FastAPI(title="Gaia Application Framework API", version="0.1.0", lifespan=lifespan)

    def runtime(request: Request) -> RuntimeEngine:
        value = request.app.state.runtime
        if value is None:
            raise RuntimeUnavailable("runtime components are not configured")
        return cast(RuntimeEngine, value)

    def trace_id(request: Request) -> str:
        return request.headers.get("X-Trace-Id") or str(uuid4())

    def replays(request: Request) -> ReplayRunner:
        value = request.app.state.replays
        if value is None:
            raise RuntimeUnavailable("evaluation components are not configured")
        return cast(ReplayRunner, value)

    def diagnostics(request: Request) -> DiagnosticExporter:
        value = request.app.state.diagnostics
        if value is None:
            raise RuntimeUnavailable("runtime components are not configured")
        return cast(DiagnosticExporter, value)

    def model_invocations(request: Request) -> SqlAlchemyModelInvocationStore:
        return cast(SqlAlchemyModelInvocationStore, request.app.state.model_invocations)

    def guardrail_decisions(request: Request) -> SqlAlchemyGuardrailDecisionStore:
        return cast(
            SqlAlchemyGuardrailDecisionStore,
            request.app.state.guardrail_decisions,
        )

    def tool_invocations(request: Request) -> SqlAlchemyToolInvocationStore:
        return cast(SqlAlchemyToolInvocationStore, request.app.state.tool_invocations)

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

    async def authenticate(request: Request) -> tuple[UserIdentity | None, JSONResponse | None]:
        """Resolve the caller identity via `active_authn`.

        Returns `(identity, None)` on success -- `identity` is `None` for a
        trusted-service caller with no end-user identity, or the authenticated
        `UserIdentity` when one was resolved -- or `(None, response)` with a 401
        `JSONResponse` when `active_authn.authenticate` raised `AuthenticationError`.
        The two failure/no-identity cases are never conflated: only the exception
        path produces a rejection.
        """

        try:
            identity = await active_authn.authenticate(request.headers)
        except AuthenticationError:
            return None, error_response(request, 401, ErrorCode.UNAUTHORIZED)
        return identity, None

    def identity_matches(identity: UserIdentity, claimed: UserIdentity) -> bool:
        return (
            identity.id == claimed.id
            and identity.organization == claimed.organization
            and set(identity.roles) == set(claimed.roles)
        )

    async def authorized_run(
        request: Request, run_id: str, identity: UserIdentity | None
    ) -> RunSnapshot | JSONResponse:
        """Fetch a Run, enforcing cross-organization isolation.

        A Run that does not exist and a Run that exists but belongs to a
        different organization than the caller's authenticated identity get
        the *same* response: 404 `RUN_NOT_FOUND`. A 403 would tell an
        unrelated caller that the resource exists, which is itself
        information it should not have (see F1 / cross-organization
        isolation). When `identity` is `None` (trusted-service / API-key
        mode) no ownership check is possible or performed -- the caller is
        trusted, per `ApiKeyAuthnProvider`'s documented trust boundary.
        """
        try:
            snapshot = await runtime(request).inspect(run_id)
        except KeyError:
            return error_response(request, 404, "RUN_NOT_FOUND")
        if identity is not None and identity.organization != snapshot.user.organization:
            return error_response(request, 404, "RUN_NOT_FOUND")
        return snapshot

    async def authorized_gate(
        request: Request, gate_id: str, identity: UserIdentity | None
    ) -> HumanGate | JSONResponse:
        """Fetch a HumanGate, enforcing cross-organization isolation via its owning Run.

        Same 404-not-403 reasoning as `authorized_run`: a Gate owned by a
        Run in a different organization is reported as `GATE_NOT_FOUND`,
        identical to a Gate that never existed.
        """
        try:
            gate = await runtime(request).get_gate(gate_id)
        except KeyError:
            return error_response(request, 404, "GATE_NOT_FOUND")
        if identity is not None:
            owner = await authorized_run(request, gate.run_id, identity)
            if isinstance(owner, JSONResponse):
                return error_response(request, 404, "GATE_NOT_FOUND")
        return gate

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return error_response(
            request,
            422,
            ErrorCode.INVALID_REQUEST,
            details={"errors": jsonable_encoder(error.errors())},
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
            authenticate,
            devtools_enabled=configured_devtools,
        )
    )
    if configured_devtools:
        from gaia.api.devtools_project import create_project_devtools_router
        from gaia.api.devtools_prompts import create_prompt_devtools_router

        app.include_router(create_prompt_devtools_router(authenticate, managed_application))
        app.include_router(create_project_devtools_router(authenticate, configured_project_root))

    @app.get("/health/live", response_model=HealthResponse)
    async def live() -> HealthResponse:
        return HealthResponse(status="ok", checks={"process": "ok"})

    @app.get("/health/ready", response_model=HealthResponse)
    async def ready(request: Request, response: Response) -> HealthResponse:
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
            },
        )

    @app.post("/v1/runs", status_code=201, response_model=RunSnapshot)
    async def create_run(
        request: Request,
        body: RunRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ) -> RunSnapshot | JSONResponse:
        identity, unauthorized = await authenticate(request)
        if unauthorized:
            return unauthorized
        if identity is not None:
            if not identity_matches(identity, body.user):
                return error_response(request, 409, ErrorCode.IDENTITY_MISMATCH)
            # The authenticated identity is the single source of truth; it
            # replaces RunRequest.user outright rather than being merged with it.
            body = body.model_copy(update={"user": identity})
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

    @app.get("/v1/runs", response_model=RunPage)
    async def list_runs(
        request: Request,
        status: RunStatus | None = None,
        scenario_id: str | None = None,
        limit: int = Query(default=RUN_LIST_DEFAULT_LIMIT, ge=1, le=RUN_LIST_MAX_LIMIT),
        cursor: str | None = None,
    ) -> RunPage | JSONResponse:
        """List Runs newest-first, scoped to the caller's organization.

        An authenticated identity only ever sees Runs belonging to its own
        `organization` -- filtered by Gaia's audit projection through the
        Runtime SPI, not after loading Runs in Python. A list endpoint is the
        easiest place to leak an entire dataset in one request.

        A trusted-service caller (API-key mode, `identity is None`) has no
        organization to scope by and sees Runs across every organization --
        the same trust boundary `authorized_run` documents for single-Run
        reads: no ownership check is possible or performed, because the
        caller is trusted per `ApiKeyAuthnProvider`.

        `limit` above `RUN_LIST_MAX_LIMIT` is rejected with 422, matching
        how `actuator.py`'s `window_hours` / `stale_after_seconds` bounds
        are enforced elsewhere in this API -- out-of-range values are a
        client error, not silently clamped.
        """
        identity, unauthorized = await authenticate(request)
        if unauthorized:
            return unauthorized
        try:
            return await runtime(request).list_runs(
                organization=identity.organization if identity is not None else None,
                status=status,
                scenario_id=scenario_id,
                limit=limit,
                cursor=cursor,
            )
        except InvalidRunCursor:
            return error_response(
                request,
                422,
                ErrorCode.INVALID_REQUEST,
                details={"field": "cursor", "reason": "cursor is malformed or expired"},
            )

    @app.get("/v1/runs/{run_id}", response_model=RunSnapshot)
    async def get_run(request: Request, run_id: str) -> RunSnapshot | JSONResponse:
        identity, unauthorized = await authenticate(request)
        if unauthorized:
            return unauthorized
        return await authorized_run(request, run_id, identity)

    @app.get(
        "/v1/runs/{run_id}/model-invocations",
        response_model=RunModelObservability,
    )
    async def list_model_invocations(
        request: Request,
        run_id: str,
    ) -> RunModelObservability | JSONResponse:
        identity, unauthorized = await authenticate(request)
        if unauthorized:
            return unauthorized
        owner = await authorized_run(request, run_id, identity)
        if isinstance(owner, JSONResponse):
            return owner
        return await model_invocations(request).for_run(run_id)

    @app.get(
        "/v1/runs/{run_id}/guardrail-decisions",
        response_model=RunGuardrailObservability,
    )
    async def list_guardrail_decisions(
        request: Request,
        run_id: str,
    ) -> RunGuardrailObservability | JSONResponse:
        identity, unauthorized = await authenticate(request)
        if unauthorized:
            return unauthorized
        owner = await authorized_run(request, run_id, identity)
        if isinstance(owner, JSONResponse):
            return owner
        return await guardrail_decisions(request).for_run(run_id)

    @app.get(
        "/v1/runs/{run_id}/tool-invocations",
        response_model=RunToolObservability,
    )
    async def list_tool_invocations(
        request: Request,
        run_id: str,
    ) -> RunToolObservability | JSONResponse:
        identity, unauthorized = await authenticate(request)
        if unauthorized:
            return unauthorized
        owner = await authorized_run(request, run_id, identity)
        if isinstance(owner, JSONResponse):
            return owner
        return await tool_invocations(request).for_run(run_id)

    @app.post("/v1/runs/{run_id}/cancel", response_model=RunSnapshot)
    async def cancel_run(
        request: Request, run_id: str, body: CancelRequest
    ) -> RunSnapshot | JSONResponse:
        identity, unauthorized = await authenticate(request)
        if unauthorized:
            return unauthorized
        owner = await authorized_run(request, run_id, identity)
        if isinstance(owner, JSONResponse):
            return owner
        try:
            return await runtime(request).cancel(run_id, body.reason)
        except KeyError:
            return error_response(request, 404, "RUN_NOT_FOUND")
        except RuntimeConflict as error:
            return error_response(request, 409, str(error))

    @app.get(
        "/v1/runs/{run_id}/human-gates",
        response_model=list[HumanGate],
    )
    async def list_run_human_gates(
        request: Request, run_id: str
    ) -> list[HumanGate] | JSONResponse:
        """Every HumanGate `run_id` opened, so a caller can name its approver.

        `GET /v1/human-gates/{gate_id}` only helps a caller who already holds
        a gate id. A Run's own snapshot never carries `decided_by`, and its
        in-flight gate references (`pending_gate_id`, `action_plan[].gate_id`)
        are cleared the moment it completes -- so once a Run is done, nothing
        else can answer "who approved this" at all. Same organization
        isolation as every other `/v1/runs/{run_id}/...` route: `authorized_run`
        turns a Run in another organization into 404, not 403.
        """

        identity, unauthorized = await authenticate(request)
        if unauthorized:
            return unauthorized
        owner = await authorized_run(request, run_id, identity)
        if isinstance(owner, JSONResponse):
            return owner
        return await runtime(request).gates_for_run(run_id)

    @app.get("/v1/runs/{run_id}/events", response_model=list[RunEvent])
    async def list_events(
        request: Request, run_id: str, after: int = 0
    ) -> list[RunEvent] | JSONResponse:
        identity, unauthorized = await authenticate(request)
        if unauthorized:
            return unauthorized
        owner = await authorized_run(request, run_id, identity)
        if isinstance(owner, JSONResponse):
            return owner
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
        identity, unauthorized = await authenticate(request)
        if unauthorized:
            return unauthorized
        owner = await authorized_run(request, run_id, identity)
        if isinstance(owner, JSONResponse):
            return owner

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
        identity, unauthorized = await authenticate(request)
        if unauthorized:
            return unauthorized
        return await authorized_gate(request, gate_id, identity)

    @app.post("/v1/human-gates/{gate_id}/decision", response_model=RunSnapshot)
    async def decide(
        request: Request, gate_id: str, body: HumanGateDecisionRequest
    ) -> RunSnapshot | JSONResponse:
        identity, unauthorized = await authenticate(request)
        if unauthorized:
            return unauthorized
        owner = await authorized_gate(request, gate_id, identity)
        if isinstance(owner, JSONResponse):
            return owner
        if identity is not None:
            # The authenticated identity is the single source of truth for who is
            # deciding and with what authority -- `body.decided_by` / `body.roles`
            # are client-submitted and therefore untrusted the moment an identity
            # is present. As with `RunRequest.user` (see `identity_matches`
            # above), a disagreement is rejected rather than silently overridden:
            # silently substituting the authenticated identity would leave the
            # caller believing its claimed `decided_by`/`roles` were the ones
            # recorded, when in fact something else was. Only when the claim
            # matches do we replace it with the identity's own values (same
            # rationale as `create_run`: it is authoritative, not merely a
            # confirmation, even when the two happen to agree).
            if body.decided_by != identity.id or set(body.roles) != set(identity.roles):
                return error_response(request, 409, ErrorCode.IDENTITY_MISMATCH)
            body = body.model_copy(
                update={"decided_by": identity.id, "roles": list(identity.roles)}
            )
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
        _, unauthorized = await authenticate(request)
        if unauthorized:
            return unauthorized
        if dependencies is None or dependencies.model_health is None:
            return error_response(request, 503, ErrorCode.MODEL_UNAVAILABLE)
        return await dependencies.model_health()

    @app.post("/v1/evals/replays", status_code=201, response_model=ReplaySnapshot)
    async def create_replay(request: Request, body: ReplayRequest) -> ReplaySnapshot | JSONResponse:
        _, unauthorized = await authenticate(request)
        if unauthorized:
            return unauthorized
        try:
            return await replays(request).run(body)
        except ValueError as error:
            return error_response(request, 422, str(error))

    @app.get("/v1/evals/replays/{replay_id}", response_model=ReplaySnapshot)
    async def get_replay(request: Request, replay_id: str) -> ReplaySnapshot | JSONResponse:
        _, unauthorized = await authenticate(request)
        if unauthorized:
            return unauthorized
        try:
            return await replays(request).get(replay_id)
        except KeyError:
            return error_response(request, 404, "REPLAY_NOT_FOUND")

    @app.get("/v1/diagnostics/runs/{run_id}/bundle", response_model=None)
    async def diagnostic_bundle(request: Request, run_id: str) -> dict[str, Any] | JSONResponse:
        identity, unauthorized = await authenticate(request)
        if unauthorized:
            return unauthorized
        owner = await authorized_run(request, run_id, identity)
        if isinstance(owner, JSONResponse):
            return owner
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
