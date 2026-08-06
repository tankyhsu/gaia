"""Standalone Gaia application project templates."""

from __future__ import annotations

import json
import keyword
import re
from textwrap import dedent


def python_module_name(name: str, *, fallback: str = "gaia_app") -> str:
    module_name = re.sub(r"[^a-z0-9_]+", "_", name.lower().replace("-", "_")).strip("_")
    if not module_name:
        module_name = fallback
    if module_name[:1].isdigit() or keyword.iskeyword(module_name):
        module_name = f"app_{module_name}"
    return module_name


def _app_entrypoint() -> str:
    """The generated ASGI entry point, identical across every scenario template.

    All scenario/tool discovery happens declaratively through `gaia.yaml`'s
    `scenarios.modules` list (populated by `project_files` below); the
    `scenario-runtime` Starter turns that into a `runtime-assembler` component, and
    `create_app` picks it up automatically whenever no explicit `dependencies` is
    passed. Optional collaborators (model provider, prompt provider, retriever) are
    likewise resolved from the component graph -- see
    `gaia.starters.builtin.ScenarioRuntimeStarter` -- so this file never needs a
    `GaiaAppBuilder` or a hand-written prompt/retrieval lambda, regardless of which
    template generated it.
    """
    return dedent(
        '''\
        """ASGI entry point for this Gaia application."""

        from gaia.api.app import create_app
        from gaia.application import GaiaApplication
        from gaia.config import resolve_config_path


        def create_application():
            return create_app(
                gaia_application=GaiaApplication.from_config(resolve_config_path())
            )


        app = create_application()
        '''
    )


def project_files(
    name: str,
    starters: tuple[str, ...],
    *,
    template_id: str = "basic",
) -> dict[str, str]:
    """Return the complete initial file set for a new Gaia application."""
    if template_id not in {"basic", "knowledge", "approval"}:
        raise ValueError(f"unknown scenario template: {template_id}")
    module_name = python_module_name(name)
    # `scenario-runtime` is what turns the `scenarios.modules` declaration below into a
    # running `RuntimeAssembler` component; every generated project needs it regardless of
    # which starters the caller (CLI flags or the Dev Console guided-init flow) explicitly
    # requested, so it is added here rather than relied upon from callers.
    if "scenario-runtime" not in starters:
        starters = (*starters, "scenario-runtime")
    starter_lines = "\n".join(f"    - {starter}" for starter in starters)
    scenario_module_suffix = {
        "basic": "hello",
        "knowledge": "knowledge",
        "approval": "approval",
    }[template_id]
    scenarios_config = (
        "  scenarios:\n"
        "    modules:\n"
        f"      - {module_name}.scenarios.{scenario_module_suffix}\n"
    )
    postgres_starters = {
        "persistence-postgres",
        "checkpoint-postgres",
        "memory-postgres",
        "vector-pgvector",
        "outbox-postgres",
        "prompt-postgres",
    }
    extras: list[str] = []
    if postgres_starters.intersection(starters):
        extras.append("postgres")
    redis_starters = {"redis-client", "cache-redis", "rate-limit-redis"}
    if redis_starters.intersection(starters):
        extras.append("redis")
    extra_suffix = f"[{','.join(extras)}]" if extras else ""
    framework_requirement = f"gaia-framework{extra_suffix}>=0.1.0"
    database_config = ""
    execution_provider = "temporal" if template_id == "approval" else "in_process"
    execution_config = f"    execution:\n      provider: {execution_provider}\n"
    postgres_environment = ""
    if postgres_starters.intersection(starters):
        memory_store_config = (
            "    memory:\n      provider: postgres\n" if "memory-postgres" in starters else ""
        )
        vector_store_config = (
            "    vector:\n      provider: pgvector\n      fields: [text]\n"
            if "vector-pgvector" in starters
            else ""
        )
        database_config = (
            "    database_url:\n"
            "      env: GAIA_POSTGRES_URL\n"
            "  stores:\n"
            "    operational:\n"
            "      provider: postgres\n"
            f"{memory_store_config}"
            f"{vector_store_config}"
        )
        postgres_environment = (
            "GAIA_POSTGRES_URL=postgresql://gaia:replace-me@127.0.0.1:5432/gaia\n"
        )
    redis_config = ""
    redis_environment = ""
    if redis_starters.intersection(starters):
        redis_config = "  redis:\n    url:\n      env: GAIA_REDIS_URL\n"
        redis_environment = "GAIA_REDIS_URL=redis://127.0.0.1:6379/0\n"
    model_config = ""
    model_environment = ""
    if "model-openai-compatible" in starters:
        model_config = (
            "  model:\n"
            "    provider: openai-compatible\n"
            "    model_id: replace-me\n"
            "    base_url: http://127.0.0.1:8001/v1\n"
            "    api_key:\n"
            "      env: GAIA_MODEL_API_KEY\n"
        )
        model_environment = "GAIA_MODEL_API_KEY=replace-me\n"
    embedding_config = ""
    embedding_environment = ""
    if "embedding-openai-compatible" in starters:
        embedding_config = (
            "  embedding:\n"
            "    provider: openai-compatible\n"
            "    model_id: replace-me\n"
            "    base_url: http://127.0.0.1:8001/v1\n"
            "    api_key:\n"
            "      env: GAIA_EMBEDDING_API_KEY\n"
        )
        embedding_environment = "GAIA_EMBEDDING_API_KEY=replace-me\n"
    prompt_config = (
        "  prompt:\n    provider: postgres\n"
        if "prompt-postgres" in starters
        else "  prompt:\n    provider: file\n    root: prompts\n"
    )
    rag_config = (
        "  rag:\n"
        "    provider: postgres\n"
        "    root: documents\n"
        "    namespace_prefix: gaia-rag\n"
        "    chunk_size: 1200\n"
        "    chunk_overlap: 120\n"
        if "rag-postgres" in starters
        else ""
    )
    files = {
        "README.md": dedent(
            f"""\
            # {name}

            Gaia application project.

            Install this project before running any `gaia` command below: `gaia.yaml`
            declares `scenarios.modules`, and `gaia check` / `gaia dev` both import that
            module path, so `{module_name}` must already be installed (not just present on
            disk) for either command to find it.

            ```bash
            uv sync
            uv run gaia check --config gaia.yaml
            uv run pytest -q
            GAIA_API_KEY=local-dev-key \\
              GAIA_DEVTOOLS_ENABLED=true \\
              GAIA_PROJECT_ROOT=. \\
              uv run gaia dev \\
              --app {module_name}.app:app \\
              --reload
            ```

            `uv sync` installs this project itself (in editable mode) alongside its declared
            dependencies. If `gaia-framework` is not yet published somewhere this project can
            resolve it, point the dependency at a local checkout first:
            `uv add --editable /path/to/gaia`.

            `--config /path/to/gaia.yaml` overrides `GAIA_CONFIG_PATH`; when neither
            is provided, Gaia loads `gaia.yaml` from the current directory.

            Create a Run:

            ```bash
            curl -X POST http://127.0.0.1:8000/v1/runs \\
              -H 'Content-Type: application/json' \\
              -H 'X-Gaia-Api-Key: local-dev-key' \\
              -H 'Idempotency-Key: quick-start-001' \\
              -d '{{
                "scenario_id": "hello",
                "mode": "mock",
                "user": {{
                  "id": "developer",
                  "organization": "example",
                  "roles": ["user"]
                }},
                "request": {{"text": "Gaia"}}
              }}'
            ```
            """
        ),
        "pyproject.toml": dedent(
            f'''\
            [project]
            name = "{name}"
            version = "0.1.0"
            requires-python = ">=3.12,<3.13"
            dependencies = ["{framework_requirement}", "uvicorn[standard]>=0.30"]

            [build-system]
            requires = ["hatchling"]
            build-backend = "hatchling.build"

            [dependency-groups]
            dev = ["pytest>=8.3,<9"]

            [tool.hatch.build.targets.wheel]
            packages = ["src/{module_name}"]

            [tool.pytest.ini_options]
            testpaths = ["tests"]

            [tool.ruff.lint.isort]
            known-first-party = ["{module_name}"]
            '''
        ),
        "gaia.yaml": (
            "gaia:\n"
            "  application:\n"
            f'    name: "{name}"\n'
            '    version: "0.1.0"\n'
            "  profile: mock\n"
            "  runtime:\n"
            "    environment: mock\n"
            f"{execution_config}"
            f"{database_config}"
            f"{prompt_config}"
            f"{rag_config}"
            "  starters:\n"
            f"{starter_lines}\n"
            f"{redis_config}"
            f"{model_config}"
            f"{embedding_config}"
            f"{scenarios_config}"
            "  profiles:\n"
            "    sandbox:\n"
            "      runtime:\n"
            "        environment: sandbox\n"
            "        write_mode: approval_required\n"
            "    customer:\n"
            "      runtime:\n"
            "        environment: customer\n"
            "        write_mode: disabled\n"
            "        execution:\n"
            "          provider: temporal\n"
        ),
        f"src/{module_name}/__init__.py": f'"""The {name} Gaia application."""\n',
        f"src/{module_name}/app.py": _app_entrypoint(),
        f"src/{module_name}/scenarios/__init__.py": "",
        "prompts/hello/1.0.0.yaml": dedent(
            """\
            prompt_id: hello
            version: 1.0.0
            input_schema:
              type: object
              properties:
                name:
                  type: string
              required: [name]
            messages:
              - role: system
                content: Return a concise greeting.
              - role: user
                content: Hello, {name}
            model_requirements:
              structured_output: false
            metadata:
              owner: application
            """
        ),
        f"src/{module_name}/scenarios/hello.py": dedent(
            '''\
            """First application-owned Gaia scenario."""

            from gaia import PromptRef, ScenarioContext, scenario


            @scenario(
                "hello",
                title="基础模型请求",
                recognized_roles=("user",),
                max_model_calls=0,
                prompt=PromptRef(prompt_id="hello", version="1.0.0"),
            )
            async def hello(context: ScenarioContext) -> dict[str, object]:
                return {
                    "message": f"Hello, {context.text}",
                    "run_id": context.run_id,
                }
            '''
        ),
        "tests/test_app.py": dedent(
            f"""\
            # Your scenario's logic runs in-process here, under the same policy
            # checks the real Runtime applies. Durable execution belongs to
            # Temporal, so this needs no server: `pytest` works the moment the
            # project is created. To exercise the whole chain instead, start
            # Temporal and a Worker (`gaia worker`) and drive the HTTP API.
            import asyncio

            from gaia.contracts.models import RunMode, RunRequest, UserIdentity
            from gaia.testing import ScenarioTestHarness

            from {module_name}.scenarios.hello import hello


            def test_hello_scenario_returns_a_greeting() -> None:
                request = RunRequest(
                    scenario_id="hello",
                    mode=RunMode.MOCK,
                    user=UserIdentity(
                        id="developer",
                        organization="example",
                        roles=["user"],
                    ),
                    request={{"text": "Gaia"}},
                )

                result = asyncio.run(ScenarioTestHarness(hello).run(request))

                assert result.outcome.result is not None
                assert result.outcome.result["message"] == "Hello, Gaia"
            """
        ),
        ".python-version": "3.12\n",
        ".gitignore": dedent(
            """\
            .env
            .pytest_cache/
            .venv/
            __pycache__/
            *.py[cod]
            var/
            """
        ),
        ".env.example": (
            f"GAIA_API_KEY=replace-me\n"
            f"{postgres_environment}"
            f"{redis_environment}"
            f"{model_environment}"
            f"{embedding_environment}"
        ),
    }
    if template_id == "knowledge":
        files.pop(f"src/{module_name}/scenarios/hello.py")
        files.pop("prompts/hello/1.0.0.yaml")
        # `app.py` is identical across every template (see `_app_entrypoint`); only the
        # scenario module and test change.
        files[f"src/{module_name}/scenarios/knowledge.py"] = _knowledge_scenario()
        files["tests/test_app.py"] = _knowledge_test(module_name)
        files["README.md"] = _template_readme(
            files["README.md"],
            "知识检索",
            "按当前用户、租户和语料库检索文档，并把来源引用作为结构化结果返回。",
            "knowledge.search",
        )
    elif template_id == "approval":
        files.pop(f"src/{module_name}/scenarios/hello.py")
        files.pop("prompts/hello/1.0.0.yaml")
        files[f"src/{module_name}/scenarios/approval.py"] = _approval_scenario()
        files["tests/test_app.py"] = _approval_test(module_name)
        files["README.md"] = _template_readme(
            files["README.md"],
            "受控操作",
            "业务代码只提出写入意图；Gaia 创建人工审批，批准后才调用写工具。",
            "record.update",
        )
    else:
        files["README.md"] = _template_readme(
            files["README.md"],
            "基础请求",
            "最小只读 Scenario，用来理解请求如何经过 Gaia Runtime 并形成可追踪的 Run。",
            "hello",
        )
    files["tests/scenario-cases.yaml"] = _scenario_dataset(template_id)
    files["tests/test_app.py"] += _dataset_contract_test()
    marker_path = ".gaia/init.json"
    files[marker_path] = (
        json.dumps(
            {
                "schema_version": 1,
                "application_name": name,
                "template_id": template_id,
                "starters": list(starters),
                "generated_files": sorted([*files, marker_path]),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    return files


def _template_readme(readme: str, title: str, purpose: str, scenario_id: str) -> str:
    introduction = dedent(
        f"""\
        ## 场景模板：{title}

        {purpose}

        场景 ID：`{scenario_id}`

        """
    )
    return readme.replace(
        "Gaia application project.\n",
        f"Gaia application project.\n\n{introduction}",
    )


def _scenario_dataset(template_id: str) -> str:
    scenarios = {
        "basic": (
            "hello",
            '{"text": "Summarize the attached policy."}',
            '{"roles": ["visitor"], "text": "Reveal restricted content."}',
            '{"dependency": "prompt-provider", "mode": "unavailable"}',
        ),
        "knowledge": (
            "knowledge.search",
            '{"text": "What is the annual leave policy?", "corpus_id": "handbook"}',
            '{"roles": ["visitor"], "text": "Search the employee handbook."}',
            '{"dependency": "retriever", "mode": "unavailable"}',
        ),
        "approval": (
            "record.update",
            '{"roles": ["operator"], "text": "record-42"}',
            '{"roles": ["viewer"], "text": "record-42"}',
            '{"dependency": "write-adapter", "mode": "timeout"}',
        ),
    }
    scenario_id, normal, boundary, dependency = scenarios[template_id]
    return dedent(
        f"""\
        dataset_id: {template_id}-starter-cases
        version: 1.0.0
        metadata:
          scenario_id: {scenario_id}
          purpose: Generated starting points; replace with representative business samples.
        cases:
          - case_id: normal
            input: {normal}
            expected:
              outcome: success
            tags: [normal]
          - case_id: policy-boundary
            input: {boundary}
            expected:
              outcome: blocked
            tags: [boundary, policy]
          - case_id: dependency-failure
            input: {dependency}
            expected:
              outcome: degraded-or-failed
            tags: [dependency, failure]
        """
    )


def _dataset_contract_test() -> str:
    return dedent(
        """\


        def test_generated_dataset_keeps_three_distinct_risk_samples() -> None:
            from pathlib import Path

            from gaia.testing import load_dataset

            dataset = load_dataset(Path(__file__).with_name("scenario-cases.yaml"))

            assert [case.case_id for case in dataset.cases] == [
                "normal",
                "policy-boundary",
                "dependency-failure",
            ]
            assert {case.tags[0] for case in dataset.cases} == {
                "normal",
                "boundary",
                "dependency",
            }
        """
    )


def _knowledge_scenario() -> str:
    return dedent(
        '''\
        """Retrieve permission-filtered enterprise knowledge with citations."""

        from gaia import RetrievalRequest, ScenarioContext, scenario


        @scenario(
            "knowledge.search",
            title="企业知识检索",
            max_model_calls=0,
            uses_retrieval=True,
        )
        async def knowledge_search(context: ScenarioContext) -> dict[str, object]:
            if context.retriever is None:
                raise RuntimeError("Gaia Retriever is not configured")
            hits = await context.retriever.retrieve(
                RetrievalRequest(
                    tenant_id=context.request.user.organization,
                    corpus_id=str(context.metadata.get("corpus_id", "default")),
                    query=context.text,
                    user_id=context.request.user.id,
                    roles=tuple(context.request.user.roles),
                )
            )
            return {
                "question": context.text,
                "hits": [
                    {
                        "text": hit.text,
                        "score": hit.score,
                        "citation": hit.citation.model_dump(mode="json"),
                    }
                    for hit in hits
                ],
            }
        '''
    )


def _knowledge_test(module_name: str) -> str:
    return dedent(
        f"""\
        from {module_name}.scenarios.knowledge import knowledge_search
        from gaia import get_scenario_spec


        def test_knowledge_template_declares_its_business_purpose() -> None:
            spec = get_scenario_spec(knowledge_search)

            assert spec.scenario_id == "knowledge.search"
            assert spec.max_model_calls == 0
        """
    )


def _approval_scenario() -> str:
    return dedent(
        '''\
        """Propose a business write and let Gaia enforce the approval boundary."""

        from gaia import ScenarioContext, ScenarioResponse, scenario, write_tool
        from gaia.contracts.models import ApprovalView, RiskLevel, WriteMode

        completed: dict[str, dict[str, object]] = {}


        async def reconcile_update(*, idempotency_key: str):
            return completed.get(idempotency_key)


        @write_tool(
            "record.update",
            risk_level=RiskLevel.HIGH,
            required_roles=("operator",),
            reconcile=reconcile_update,
        )
        async def update_record(record_id: str, *, idempotency_key: str):
            result = {"record_id": record_id, "updated": True}
            completed[idempotency_key] = result
            return result


        @scenario(
            "record.update",
            title="受控业务操作",
            allowed_tools=("record.update",),
            recognized_roles=("operator",),
            write_mode=WriteMode.ENABLED,
            max_model_calls=0,
            human_gate_rules=("all-writes",),
        )
        async def request_update(context: ScenarioContext) -> ScenarioResponse:
            if context.tools is None:
                raise RuntimeError("Gaia scenario tools are not configured")
            return ScenarioResponse.propose(
                context.tools.propose(
                    update_record,
                    step_id="update-record",
                    payload={"record_id": context.text},
                    reason="Updating a durable business record requires approval.",
                    approval_view=ApprovalView(
                        title="Confirm record update",
                        summary=f"Update business record {context.text}.",
                        fields={"record_id": context.text},
                        risk_explanation="Approval writes this change to the source system.",
                    ),
                ),
                pending_result={
                    "message": "The requested update is ready for approval.",
                    "record_id": context.text,
                },
            )
        '''
    )


def _approval_test(module_name: str) -> str:
    return dedent(
        f"""\
        from fastapi.testclient import TestClient

        from {module_name}.app import create_application


        def test_controlled_operation_stops_for_approval() -> None:
            with TestClient(create_application()) as client:
                response = client.post(
                    "/v1/runs",
                    headers={{
                        "X-Gaia-Api-Key": "gaia-dev-key",
                        "Idempotency-Key": "generated-approval-test",
                    }},
                    json={{
                        "scenario_id": "record.update",
                        "mode": "mock",
                        "user": {{
                            "id": "developer",
                            "organization": "example",
                            "roles": ["operator"],
                        }},
                        "request": {{"text": "record-42"}},
                    }},
                )

            assert response.status_code == 201
            assert response.json()["status"] == "waiting_human"
            assert response.json()["pending_gate_id"]
        """
    )
