# Gaia 应用开发 Quick Start

这份文档面向使用 Gaia 开发 AI 应用的工程师。最短路径不是先理解 Runtime 或 LangGraph，而是创建
一个独立应用、实现普通异步函数，再由 Gaia 把它接入统一的状态、幂等、预算、HumanGate 和审计
边界。

## 1. 创建应用

当前 Gaia 尚未发布到公共包仓库，需要 Python 3.12 和
[uv](https://docs.astral.sh/uv/)。

```bash
export GAIA_REPO=/absolute/path/to/gaia
export APP_DIR=/absolute/path/to/hello-gaia

cd "$GAIA_REPO"
uv sync --all-groups
uv run gaia init "$APP_DIR" --name hello-gaia

cd "$APP_DIR"
uv add --editable "$GAIA_REPO"
uv sync
uv run gaia check --config gaia.yaml
uv run pytest -q
```

`gaia init` 默认生成基础请求模板。也可以通过参数直接选择场景和组件：

```bash
uv run gaia init "$APP_DIR" \
  --template knowledge \
  --component prompt-registry
```

场景模板负责生成能读懂的应用代码，组件选择负责激活相应 Starter。当前内置：

| 模板 | 用途 |
| --- | --- |
| `basic` | 处理文本和文档：总结、分类、信息抽取或内容生成 |
| `knowledge` | 基于企业知识回答：按权限检索资料并标明来源 |
| `approval` | 连接并操作业务系统：调用接口并在关键步骤人工确认 |

Dev Console 会在三类模板下分别展示“简历阅读”“员工手册”“请假办理”参考示例，帮助业务
构建者先理解可实现的体验，再生成自己的项目起点。参考示例通过独立 Showcase 应用提供，
不把 HR 业务定义写入 Gaia 核心模块。

本地同时运行多个应用时，可以分别指定 Console 要观察的 API 和参考示例地址：

```bash
VITE_GAIA_API_TARGET=http://localhost:8001 \
VITE_GAIA_SHOWCASE_URL=http://localhost:4173 \
npm --prefix apps/web run dev -- --port 4174
```

首次本地启动并开启 DevTools 后，Quick Start 页面提供同样的场景和组件选择。页面写入能力只对
仍包含 `.gaia/init.json` 初始化标记的项目开放；完成初始化后自动关闭，生产 API 不注册这些路由。

正式交付时应把 editable 依赖改为固定版本的内部包或 wheel。

生成项目的主要文件：

| 文件 | 用途 |
| --- | --- |
| `src/hello_gaia/app.py` | ASGI 入口和 Scenario 注册 |
| `src/hello_gaia/scenarios/hello.py` | 第一个可运行 Scenario |
| `prompts/hello/1.0.0.yaml` | Git 管理的不可变 Prompt Artifact |
| `gaia.yaml` | Profile、Starter 和基础设施配置 |
| `tests/test_app.py` | 穿过真实 Gaia Runtime 的应用测试 |
| `.env.example` | 环境变量清单，不包含真实密钥 |

`gaia check` 只验证配置和装配，不连接外部系统；启用 PostgreSQL、Redis、模型或 Embedding 后，
再用 `uv run gaia doctor --config gaia.yaml` 做显式连通性探测。

## 2. 启动和调用

```bash
GAIA_API_KEY=local-dev-key \
  GAIA_DEVTOOLS_ENABLED=true \
  GAIA_PROJECT_ROOT=. \
  uv run gaia dev --app hello_gaia.app:app --reload
```

另开终端：

```bash
curl -fsS http://127.0.0.1:8000/health/live

curl -fsS -X POST http://127.0.0.1:8000/v1/runs \
  -H 'Content-Type: application/json' \
  -H 'X-Gaia-Api-Key: local-dev-key' \
  -H 'Idempotency-Key: quick-start-001' \
  -d '{
    "scenario_id": "hello",
    "mode": "mock",
    "user": {
      "id": "developer",
      "organization": "example",
      "roles": ["user"]
    },
    "request": {"text": "Gaia"}
  }'
```

返回状态应为 `succeeded`，结果包含 `Hello, Gaia`。用相同 Idempotency-Key 和相同请求重复调用，
返回同一个 Run；相同 Key 配不同请求会被拒绝。

`--reload` 必须与 `--app` 一起使用。`gaia dev` 不加载 `.env` 文件，请由 shell、IDE 或部署平台
显式注入环境变量。

## 3. 写一个只读场景

`@scenario` 只附加不可变元数据，不建立连接、不创建 Client，也不把函数写进全局注册表：

```python
from gaia import PromptRef, ScenarioContext, scenario


@scenario(
    "summarize",
    prompt=PromptRef(prompt_id="summarize", version="1.0.0"),
    recognized_roles=("user",),
    max_model_calls=1,
)
async def summarize(context: ScenarioContext) -> dict[str, object]:
    return {
        "source": context.text,
        "summary": context.text[:120],
    }
```

在 `app.py` 中显式注册：

```python
dependencies=ApiDependencies.from_scenarios(
    gaia_application.config,
    hello,
    summarize,
    prompt_provider=lambda: gaia_application.get_component("prompt-file"),
)
```

普通函数由 `FunctionScenarioRunner` 适配到唯一的 `ScenarioRunner` SPI。它不需要 LangGraph，
但仍经过 `PersistentRuntimeEngine`，不会形成第二条绕开安全边界的执行链。

## 4. 使用文件 Prompt

文件 Provider 使用固定路径：

```text
prompts/<prompt_id>/<version>.yaml
```

Artifact 示例：

```yaml
prompt_id: summarize
version: 1.0.0
input_schema:
  type: object
  properties:
    text:
      type: string
  required: [text]
messages:
  - role: system
    content: Produce a concise, factual summary.
  - role: user
    content: "{text}"
model_requirements:
  structured_output: false
metadata:
  owner: application
```

通过应用生命周期启动后取得 Provider，并解析精确版本：

```python
from typing import cast

from gaia import PromptProvider, PromptRef

provider = cast(
    PromptProvider,
    gaia_application.get_component("prompt-file"),
)
artifact = await provider.resolve(
    PromptRef(prompt_id="summarize", version="1.0.0"),
)
```

每次内容修改都创建新版本文件，不覆盖已经运行过的版本。文件 Provider 只在 `resolve()` 时读取，
因此 import、Starter 装配和 `gaia check` 保持零文件 I/O。环境发布指针、动态发布和回滚属于后续
Prompt Registry，不由文件 Provider 隐式模拟。Run 创建时会把精确版本和内容哈希固定到
`VersionBundle.prompt`。

### 高频调整使用 Prompt Registry

多人协作、无需重启发布和快速回滚的应用选择 PostgreSQL Registry：

```bash
uv run gaia init "$APP_DIR" \
  --name hello-gaia \
  --starter prompt-postgres

export GAIA_POSTGRES_URL=postgresql://gaia:password@127.0.0.1:5432/gaia
uv run gaia migrate --config gaia.yaml
```

生命周期命令：

```bash
uv run gaia prompt import prompts/summary/1.0.0.yaml \
  --config gaia.yaml --actor developer

uv run gaia prompt validate summary 1.0.0 \
  --report reports/summary-1.0.0.json \
  --config gaia.yaml --actor qa

uv run gaia prompt publish summary 1.0.0 \
  --environment sandbox \
  --config gaia.yaml --actor release-manager

uv run gaia prompt rollback summary 1.0.0 \
  --environment sandbox \
  --config gaia.yaml --actor release-manager
```

验证报告必须来自 Gaia Test Kit、整体通过，并在 `subject` 中精确绑定 `prompt_id`、
`prompt_version` 和 `prompt_content_hash`。发布只移动环境指针；新 Run 读取新指针，已存在 Run、
等待 HumanGate 的 Run 和 Idempotency-Key 重试继续使用持久化的旧版本。

开发期 Prompt Workspace 仅在 PostgreSQL Registry 已装配且显式开启时出现：

```bash
GAIA_DEVTOOLS_ENABLED=true make dev-api
# 另开终端
make dev-console
```

默认 API 不注册 `/devtools/prompts` 写路由，生产部署不启用该开关。

## 5. 增加受控写入

写工具不能只靠函数签名推断安全性。它必须声明风险、角色、可用环境和 `reconcile`；后者用于超时
或进程中断后确认外部系统是否已经执行。

```python
from gaia import write_tool
from gaia.contracts.models import RiskLevel

completed: dict[str, dict[str, object]] = {}


async def reconcile(*, idempotency_key: str) -> dict[str, object] | None:
    return completed.get(idempotency_key)


@write_tool(
    "publish-document",
    risk_level=RiskLevel.HIGH,
    required_roles=("operator",),
    reconcile=reconcile,
)
async def publish_document(
    document_id: str,
    *,
    idempotency_key: str,
) -> dict[str, object]:
    result = {"document_id": document_id, "status": "published"}
    completed[idempotency_key] = result
    return result
```

Scenario 只提出副作用，不直接调用写函数：

```python
from gaia import ScenarioResponse, ScenarioSideEffect
from gaia.contracts.models import RiskLevel, WriteMode


@scenario(
    "document.publish",
    allowed_tools=("publish-document",),
    recognized_roles=("operator",),
    write_mode=WriteMode.ENABLED,
    max_model_calls=0,
)
async def publish(context: ScenarioContext) -> ScenarioResponse:
    return ScenarioResponse.propose(
        ScenarioSideEffect(
            step_id="publish",
            tool_name="publish-document",
            payload={"document_id": context.text},
            reason="Publishing changes a durable business record.",
            risk_level=RiskLevel.HIGH,
        )
    )
```

把场景和工具显式装进应用：

```python
dependencies=ApiDependencies.from_scenarios(
    gaia_application.config,
    hello,
    publish,
    write_tools=(publish_document,),
)
```

创建 Run 后，高风险写入返回 `waiting_human` 和 `pending_gate_id`，此时工具尚未执行。审批：

```bash
curl -fsS -X POST \
  "http://127.0.0.1:8000/v1/human-gates/$GATE_ID/decision" \
  -H 'Content-Type: application/json' \
  -H 'X-Gaia-Api-Key: local-dev-key' \
  -d '{
    "decision": "approved",
    "decided_by": "approver-1",
    "roles": ["approver"],
    "comment": "Approved."
  }'
```

Gaia 在批准后执行工具，并使用 Run 与步骤派生的稳定幂等键。风险声明、策略、环境和工具定义不一致
时，Runtime 在外部写入前拒绝请求。

## 6. Profile 和基础设施

新项目默认使用 SQLite、mock 模型和文件 Prompt。先在无外部凭据的环境跑通第一条链路，再按需
选择 Starter：

```bash
uv run gaia init "$APP_DIR" \
  --name hello-gaia \
  --starter model-openai-compatible \
  --starter persistence-postgres
```

默认安全语义：

| Profile | 环境 | 默认写入模式 |
| --- | --- | --- |
| `mock` | 本地假实现 | `enabled` |
| `sandbox` | 隔离测试系统 | `approval_required` |
| `customer` | 客户环境 | `disabled` |

切换前先运行：

```bash
uv run gaia check --config gaia.yaml --set profile=sandbox
uv run gaia doctor --config gaia.yaml --set profile=sandbox
```

不要只修改 Profile 名称就连接客户系统。真实接入还需要 SecretRef、工具白名单、风险等级、审批
策略和目标 Adapter。

## 7. AI 行为测试

应用自己的脱敏真实请求应维护为版本化 Golden Dataset。Gaia 提供 Dataset、Evaluator 和质量门禁
框架，业务 Rubric 和 Case 仍由应用所有：

```python
gate = PassRateGate(
    evaluator_id="application-judge",
    metric="answer_quality",
    case_threshold=4.0,
    suite_threshold=0.95,
    critical_tags=("critical",),
    slice_thresholds={"boundary": 0.90},
)
```

这类统计性门禁是 AI 应用的发布测试，不进入生产 Runtime。具体契约见
[Gaia Test Kit 设计](docs/施工图/08-Gaia-Test-Kit设计.md)。

## 8. 模型调用可观测

应用通过 `InstrumentedModelProvider` 包装真实 Provider，并在调用时传入 Run 和 Prompt 的关联
信息。Wrapper 统一记录 Token、耗时、重试、错误和可选成本，但只保存请求/响应哈希，不保存
Prompt 或模型响应正文：

```python
from gaia import ModelCallContext
from gaia.observability import InstrumentedModelProvider, SqlAlchemyModelInvocationStore

provider = InstrumentedModelProvider(
    application_model_provider,
    SqlAlchemyModelInvocationStore(session_factory),
)

result = await provider.generate_structured(
    profile=model_profile,
    messages=messages,
    output_schema=Output,
    timeout_seconds=30,
    context=ModelCallContext(
        run_id=run_id,
        scenario_id="summarize",
        prompt_version="summarize:2.1.0",
        prompt_content_hash=prompt_hash,
    ),
)
```

`GET /v1/runs/{run_id}/model-invocations` 返回该 Run 的模型摘要。需要把同样的安全属性送往现有
观测平台时，安装 `gaia-framework[otel]` 并组合 `OpenTelemetryModelInvocationSink`；未启用时
Gaia 不加载 OpenTelemetry。

## 9. 最小有引用 RAG

需要文档检索时显式增加 `rag-postgres`。它会带入 PostgreSQL Memory、pgvector 和
OpenAI-compatible Embedding 依赖；未选择 Vector Store 时不会自动激活：

```bash
uv run gaia init "$APP_DIR" --name knowledge-app --starter rag-postgres
```

启动后的 `rag-postgres` 组件提供 `RagPipeline`：

```python
from gaia import DocumentAccess, DocumentSource, RetrievalRequest

rag = gaia_application.get_component("rag-postgres")
await rag.ingest(
    DocumentSource(
        document_id="expense-policy",
        tenant_id="tenant-a",
        corpus_id="policies",
        version="2.0.0",
        uri="expense-policy.md",
        media_type="text/markdown",
        access=DocumentAccess(allowed_roles=("finance",)),
    )
)
hits = await rag.retrieve(
    RetrievalRequest(
        tenant_id="tenant-a",
        corpus_id="policies",
        query="发票提交期限",
        user_id="alice",
        roles=("finance",),
    )
)
```

每个 Hit 都包含 `Citation`：文档 ID、版本、URI、Chunk 哈希、位置和本次通过权限校验的依据。
重复摄取相同版本与内容不会重写；更新通过 active generation 切换，删除会同时撤销 manifest
和 Chunk。

内置 `Utf8TextParser` 只作为文本和 Markdown 参考实现。PDF、Office、OCR 或行业格式应由应用
替换 `DocumentParser`，Gaia Core 不绑定 Docling 或厂商解析服务。

## 10. 交付前门禁

- `uv run gaia check --config gaia.yaml` 成功；
- 启用真实依赖时，`uv run gaia doctor --config gaia.yaml` 成功；
- `uv run pytest -q` 成功；
- `/health/ready` 返回 `ok`；
- `/actuator/components` 能解释组件来源和装配原因；
- `/actuator/runtime` 能显示 Run、等待、错误和资源争用摘要；
- 至少一个 Scenario 穿过真实 Gaia Runtime；
- 所有写操作通过 Tool、Policy、HumanGate 和幂等边界；
- Prompt 使用固定版本，Golden Dataset 能回归关键行为；
- README 写明启动命令、环境变量和未接通的外部系统。

达到这些条件，Gaia 才真正成为应用的开发底座，而不只是一个被安装的依赖。
