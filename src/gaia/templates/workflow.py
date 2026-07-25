"""Application-owned deterministic workflow extension templates."""

from __future__ import annotations

from textwrap import dedent

from gaia.templates.project import python_module_name


def workflow_files(application_module: str, name: str) -> dict[str, str]:
    workflow_module = python_module_name(name, fallback="workflow")
    class_name = "".join(part.capitalize() for part in workflow_module.split("_"))
    return {
        f"src/{application_module}/workflows/{workflow_module}.py": dedent(
            f'''\
            """Application-owned {name} workflow."""

            from __future__ import annotations

            import operator
            from typing import Annotated, Literal, TypedDict

            from langgraph.graph import END, START, StateGraph


            class {class_name}State(TypedDict, total=False):
                run_id: str
                input: str
                route: Literal["process", "reject"]
                result: dict[str, object]
                visited: Annotated[list[str], operator.add]


            def _validate(state: {class_name}State) -> {class_name}State:
                route = "process" if state.get("input", "").strip() else "reject"
                return {{"route": route, "visited": ["validate"]}}


            def _route(state: {class_name}State) -> str:
                return state["route"]


            def _process(state: {class_name}State) -> {class_name}State:
                return {{
                    "result": {{"accepted_input": state["input"]}},
                    "visited": ["process"],
                }}


            def _reject(_: {class_name}State) -> {class_name}State:
                return {{
                    "result": {{"error_code": "INVALID_REQUEST"}},
                    "visited": ["reject"],
                }}


            def build_{workflow_module}_workflow():
                builder = StateGraph({class_name}State)
                builder.add_node("validate", _validate)
                builder.add_node("process", _process)
                builder.add_node("reject", _reject)
                builder.add_edge(START, "validate")
                builder.add_conditional_edges(
                    "validate",
                    _route,
                    {{"process": "process", "reject": "reject"}},
                )
                builder.add_edge("process", END)
                builder.add_edge("reject", END)
                return builder.compile()
            '''
        ),
        f"tests/workflows/test_{workflow_module}.py": dedent(
            f"""\
            from {application_module}.workflows.{workflow_module} import (
                build_{workflow_module}_workflow,
            )


            def test_{workflow_module}_routes_valid_input_to_process() -> None:
                result = build_{workflow_module}_workflow().invoke(
                    {{"run_id": "run-1", "input": "example", "visited": []}}
                )

                assert result["visited"] == ["validate", "process"]
                assert result["result"] == {{"accepted_input": "example"}}


            def test_{workflow_module}_routes_empty_input_to_reject() -> None:
                result = build_{workflow_module}_workflow().invoke(
                    {{"run_id": "run-2", "input": "", "visited": []}}
                )

                assert result["visited"] == ["validate", "reject"]
                assert result["result"]["error_code"] == "INVALID_REQUEST"
            """
        ),
    }
