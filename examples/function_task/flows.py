"""Reference scenarios for the `function_task` example.

Five handlers, all plain business logic:

- `function_task.inspect_resource` is read-only: it calls a read tool and returns a
  mapping. No model call, no approval.
- `function_task.request_publish` proposes a write via `ScenarioResponse.propose`, so
  the Temporal Workflow routes it through Gaia's HumanGate policy contract before the
  write Activity executes.
  Its `rules_version` is derived with `fingerprint(tools)` instead of a hand-typed
  literal: the governing "rule" here -- publish is HIGH risk and needs approval -- lives
  in `tools.publish_resource`'s `write_tool(...)` declaration, so a change to that
  declaration (or to the mutation logic backing it) changes the fingerprint on the next
  import. A hand-typed `rules_version="1.0.0"` would happily keep reporting "1.0.0" even
  after someone weakened the risk level, letting the audit evidence lie about which
  rules produced the decision.
- `function_task.escalate_resource` hands off to `resource_specialist`, an
  `@agent_handler` target, to show the declarative handoff path: the scenario names its
  own outgoing edge with `@scenario(allowed_handoffs=...)`, and `resource_specialist`
  produces the run's terminal result.
- `function_task.request_publish_and_notify` proposes the same kind of write as
  `request_publish` but names a `continue_with` handler, so `notify_after_publish` (an
  `@continuation_handler`) runs automatically once the write is approved and executed,
  to show the declarative post-write-continuation path.
- `function_task.reject_request` returns a rule-backed refusal without creating a
  HumanGate, giving the standalone framework demo one honest blocked outcome.

Everything about *how* the write gets authorized, persisted, and replayed after
approval, and how the handoff/continuation routing table gets assembled, is the
framework's job, wired entirely through discovery and `gaia.yaml`.
"""

from __future__ import annotations

from gaia import (
    ScenarioContext,
    ScenarioResponse,
    ScenarioSideEffect,
    ScenarioTrace,
    agent_handler,
    continuation_handler,
    fingerprint,
    scenario,
)
from gaia.contracts.models import (
    ActorType,
    ApprovalView,
    ErrorCode,
    RiskLevel,
    RunStatus,
    WriteMode,
)

from . import tools
from .tools import lookup_resource


@scenario(
    "function_task.inspect_resource",
    allowed_tools=("function_task.lookup_resource",),
    max_model_calls=0,
)
async def inspect_resource(context: ScenarioContext) -> dict[str, object]:
    assert context.tools is not None
    looked_up = await context.tools.call(lookup_resource, resource_id=context.text)
    return {"resource_id": context.text, "status": looked_up.data["status"]}


@scenario("function_task.reject_request", max_model_calls=0)
async def reject_request(context: ScenarioContext) -> ScenarioResponse:
    del context
    return ScenarioResponse(
        status=RunStatus.BLOCKED,
        error_code=ErrorCode.FORBIDDEN,
        trace=(
            ScenarioTrace(
                "apply_demo_policy",
                actor=ActorType.RULE,
                rule_refs=("RULE-FUNCTION-TASK-DENY",),
            ),
        ),
        decision_step="apply_demo_policy",
        decision_rule_refs=("RULE-FUNCTION-TASK-DENY",),
    )


@scenario(
    "function_task.request_publish",
    allowed_tools=("function_task.publish_resource",),
    write_mode=WriteMode.ENABLED,
    max_model_calls=0,
    rules_version=fingerprint(tools),
)
async def request_publish(context: ScenarioContext) -> ScenarioResponse:
    return ScenarioResponse.propose(
        ScenarioSideEffect(
            step_id="publish",
            tool_name="function_task.publish_resource",
            payload={"resource_id": context.text},
            reason="Publishing changes a durable business record.",
            risk_level=RiskLevel.HIGH,
            approval_view=ApprovalView(
                title="Publish resource",
                summary="Mark the resource as published.",
                fields={"resource_id": context.text},
                risk_explanation="This changes a durable business record.",
            ),
        ),
        pending_result={"resource_id": context.text, "status": "pending_publish"},
    )


@scenario(
    "function_task.escalate_resource",
    max_model_calls=0,
    allowed_handoffs=("resource_specialist",),
)
async def escalate_resource(context: ScenarioContext) -> ScenarioResponse:
    return ScenarioResponse.handoff_to(
        "resource_specialist",
        input={"resource_id": context.text},
        reason="Needs specialist review before further action.",
    )


@agent_handler("resource_specialist")
async def resource_specialist(context: ScenarioContext) -> dict[str, object]:
    resource_id = context.handoff_input["resource_id"]
    return {"resource_id": resource_id, "status": "reviewed_by_specialist"}


@scenario(
    "function_task.request_publish_and_notify",
    allowed_tools=("function_task.publish_resource",),
    write_mode=WriteMode.ENABLED,
    max_model_calls=0,
)
async def request_publish_and_notify(context: ScenarioContext) -> ScenarioResponse:
    return ScenarioResponse.propose(
        ScenarioSideEffect(
            step_id="publish",
            tool_name="function_task.publish_resource",
            payload={"resource_id": context.text},
            reason="Publishing changes a durable business record.",
            risk_level=RiskLevel.HIGH,
            approval_view=ApprovalView(
                title="Publish resource",
                summary="Mark the resource as published.",
                fields={"resource_id": context.text},
                risk_explanation="This changes a durable business record.",
            ),
        ),
        pending_result={"resource_id": context.text, "status": "pending_publish"},
        continue_with="notify_after_publish",
    )


@continuation_handler("notify_after_publish")
async def notify_after_publish(context: ScenarioContext) -> dict[str, object]:
    return {**context.action_result, "notified": True}
