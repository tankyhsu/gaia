"""LangGraph decision workflow for the controlled-task golden scenario.

The graph is deterministic and side-effect free. Runtime persists the gate and executes
the command; this graph only pauses, resumes and records the selected route.
"""

from __future__ import annotations

import operator
import sqlite3
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt


class ControlledTaskState(TypedDict, total=False):
    run_id: str
    request_text: str
    intent: dict[str, Any]
    user: dict[str, Any]
    resource: dict[str, Any] | None
    context_gaps: list[str]
    gate_id: str
    approval_decision: str
    outcome: Literal["read", "no_change", "approval", "blocked", "degraded"]
    error_code: str | None
    rule_id: str
    result: dict[str, Any]
    proposal: dict[str, Any]
    visited: Annotated[list[str], operator.add]


def _visit(name: str) -> ControlledTaskState:
    return {"visited": [name]}


def _validate_request(_: ControlledTaskState) -> ControlledTaskState:
    return _visit("validate_request")


def _interpret_intent(_: ControlledTaskState) -> ControlledTaskState:
    return _visit("interpret_intent")


def _authorize_context(_: ControlledTaskState) -> ControlledTaskState:
    return _visit("authorize_context")


def _load_context(_: ControlledTaskState) -> ControlledTaskState:
    return _visit("load_context")


def _read_resource(_: ControlledTaskState) -> ControlledTaskState:
    return _visit("read_resource")


def _evaluate_rules(state: ControlledTaskState) -> ControlledTaskState:
    intent = state.get("intent", {})
    user = state.get("user", {})
    resource = state.get("resource")
    if not intent.get("operation") or not intent.get("resource_id"):
        return {
            **_visit("evaluate_rules"),
            "outcome": "blocked",
            "error_code": "INVALID_REQUEST",
            "rule_id": "RULE-CT-001",
        }
    if resource is None or resource.get("organization") != user.get("organization"):
        return {
            **_visit("evaluate_rules"),
            "outcome": "blocked",
            "error_code": "FORBIDDEN",
            "rule_id": "RULE-CT-004",
        }
    if state.get("context_gaps"):
        return {
            **_visit("evaluate_rules"),
            "outcome": "degraded",
            "error_code": "CONTEXT_INSUFFICIENT",
            "rule_id": "RULE-CT-009",
        }
    roles = set(user.get("roles", []))
    if intent["operation"] == "inspect":
        if not roles.intersection(resource.get("readable_roles", [])):
            return {
                **_visit("evaluate_rules"),
                "outcome": "blocked",
                "error_code": "FORBIDDEN",
                "rule_id": "RULE-CT-005",
            }
        return {
            **_visit("evaluate_rules"),
            "outcome": "read",
            "error_code": None,
            "rule_id": "RULE-CT-002",
            "result": dict(resource),
        }
    if not intent.get("target_status") or not intent.get("reason"):
        return {
            **_visit("evaluate_rules"),
            "outcome": "blocked",
            "error_code": "INVALID_REQUEST",
            "rule_id": "RULE-CT-003",
        }
    if "operator" not in roles:
        return {
            **_visit("evaluate_rules"),
            "outcome": "blocked",
            "error_code": "FORBIDDEN",
            "rule_id": "RULE-CT-006",
        }
    if resource.get("status") == intent["target_status"]:
        return {
            **_visit("evaluate_rules"),
            "outcome": "no_change",
            "error_code": None,
            "rule_id": "RULE-CT-007",
            "result": {**resource, "no_change": True},
        }
    return {
        **_visit("evaluate_rules"),
        "outcome": "approval",
        "error_code": None,
        "rule_id": "RULE-CT-008",
        "proposal": {
            "resource_id": intent["resource_id"],
            "target_status": intent["target_status"],
        },
    }


def _route_after_rules(state: ControlledTaskState) -> str:
    return state["outcome"]


def _return_read_result(_: ControlledTaskState) -> ControlledTaskState:
    return _visit("return_read_result")


def _return_no_change(_: ControlledTaskState) -> ControlledTaskState:
    return _visit("return_no_change")


def _propose_side_effect(_: ControlledTaskState) -> ControlledTaskState:
    return _visit("propose_side_effect")


def _create_human_gate(state: ControlledTaskState) -> ControlledTaskState:
    decision = interrupt(
        {
            "gate_id": state.get("gate_id"),
            "run_id": state["run_id"],
            "proposal": state["proposal"],
            "rule_id": state["rule_id"],
        }
    )
    if not isinstance(decision, dict) or decision.get("decision") not in {
        "approved",
        "rejected",
    }:
        raise ValueError("resume payload must contain decision=approved|rejected")
    if decision["decision"] == "rejected":
        return {
            **_visit("create_human_gate"),
            "approval_decision": "rejected",
            "outcome": "blocked",
            "error_code": "HUMAN_GATE_REJECTED",
        }
    return {
        **_visit("create_human_gate"),
        "approval_decision": "approved",
    }


def _route_after_gate(state: ControlledTaskState) -> str:
    return "execute" if state.get("approval_decision") == "approved" else "finalize"


def _execute_side_effect(_: ControlledTaskState) -> ControlledTaskState:
    return _visit("execute_side_effect")


def _finalize(_: ControlledTaskState) -> ControlledTaskState:
    return _visit("finalize")


def create_sqlite_checkpointer(database_path: Path) -> SqliteSaver:
    """LangGraph owns only its checkpoint tables in this SQLite database."""
    connection = sqlite3.connect(database_path, check_same_thread=False)
    return SqliteSaver(connection)


def build_controlled_task_graph(checkpointer: Any | None = None) -> Any:
    graph = StateGraph(ControlledTaskState)
    nodes: dict[str, Any] = {
        "validate_request": _validate_request,
        "interpret_intent": _interpret_intent,
        "authorize_context": _authorize_context,
        "load_context": _load_context,
        "read_resource": _read_resource,
        "evaluate_rules": _evaluate_rules,
        "return_read_result": _return_read_result,
        "return_no_change": _return_no_change,
        "propose_side_effect": _propose_side_effect,
        "create_human_gate": _create_human_gate,
        "execute_side_effect": _execute_side_effect,
        "finalize": _finalize,
    }
    for name, action in nodes.items():
        graph.add_node(name, action)

    graph.add_edge(START, "validate_request")
    graph.add_edge("validate_request", "interpret_intent")
    graph.add_edge("interpret_intent", "authorize_context")
    graph.add_edge("authorize_context", "load_context")
    graph.add_edge("load_context", "read_resource")
    graph.add_edge("read_resource", "evaluate_rules")
    graph.add_conditional_edges(
        "evaluate_rules",
        _route_after_rules,
        {
            "read": "return_read_result",
            "no_change": "return_no_change",
            "approval": "propose_side_effect",
            "blocked": "finalize",
            "degraded": "finalize",
        },
    )
    graph.add_edge("return_read_result", "finalize")
    graph.add_edge("return_no_change", "finalize")
    graph.add_edge("propose_side_effect", "create_human_gate")
    graph.add_conditional_edges(
        "create_human_gate",
        _route_after_gate,
        {"execute": "execute_side_effect", "finalize": "finalize"},
    )
    graph.add_edge("execute_side_effect", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
