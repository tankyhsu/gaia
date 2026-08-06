# Python API

这一页从 Gaia 公开 Python 类型、函数和 docstring 自动生成。应用优先依赖 `gaia` 顶层导出的
公共 API，不要直接依赖 Runtime 或 Persistence 内部模块。

## Scenario

::: gaia
    options:
      members:
        - ScenarioContext
        - ScenarioContinuation
        - ScenarioResponse
        - ScenarioSideEffect
        - ScenarioTrace
        - ScenarioSpec
        - scenario
        - get_scenario_spec

### 审批后的动态续接

```python
async def notify_requester(context: ScenarioContext) -> ScenarioResponse:
    ticket_id = context.action_result["ticket_id"]
    return ScenarioResponse.propose(
        context.tools.propose(
            send_notification,
            step_id="notify-requester",
            payload={"message": f"Ticket {ticket_id} was created."},
            reason="Notify the requester with the generated ticket ID.",
        )
    )

async def create_request(context: ScenarioContext) -> ScenarioResponse:
    return ScenarioResponse.propose(
        context.tools.propose(
            create_ticket,
            step_id="create-ticket",
            payload={"subject": context.text},
            reason="Create the approved ticket.",
        ),
        continue_with="notify-requester",
        continuation_input={"requester": context.request.user.id},
    )

builder.continuations({"notify-requester": notify_requester})
```

Runtime 会持久化命名 Handler、`continuation_input` 和成功后的 `action_result`。它不会序列化或
恢复 Python 协程栈。

### 版本指纹：让 `rules_version` 不会撒谎

`@scenario(rules_version="1.0.0", ...)` 里的 `rules_version`、`policy_version`、
`toolset_version`、`prompt_version` 都是手填字符串，会被原样写进每个 Run 的
`VersionBundle` 审计证据。手填字符串的问题不是麻烦，而是**会漂移**：改了
`rules.py` 里的判定逻辑却忘记把字符串从 `"1.0.0"` 改成 `"1.0.1"`，`VersionBundle`
从此持续报告一个不再对应实际执行代码的版本号。对一个把"可审计的受控执行"当作
核心价值的框架来说，一份可以悄悄失真却仍然被信任的版本证据，比完全没有版本证据
更危险——它看起来权威，实际上已经不再描述真正发生的事情。

顶层公共 API `gaia.fingerprint` 把版本号变成内容的函数，而不是需要人记得维护的
字面量：

```python
from gaia import fingerprint

from . import rules

@scenario(
    "order-review",
    rules_version=fingerprint(rules),          # 'sha256:3f1a9c0d2e4b'
    ...,
)
async def order_review(context: ScenarioContext) -> ScenarioResponse:
    ...
```

`rules.py` 的内容一变，下次导入时 `rules_version` 自动变化——没有字面量可忘记更新。
`fingerprint` 也接受文件路径、`Mapping`/`Sequence`（走 canonical JSON），常用于把
一份配置字典也纳入指纹：

```python
digest = fingerprint(payload, qualified=False)  # '3f1a9c0d2e4b'，可以安全拼进版本号
```

`qualified=False` 去掉 `sha256:` 前缀（连同其中的冒号）：带冒号的版本号一旦被拼进
PEP 440 本地版本号（例如 `1.0.0+ovr.<digest>`）就会非法，冒号不在 PEP 440 允许的
字符集里。凡是要把指纹嵌入另一个版本号的场景，都必须用 `qualified=False`。

`fingerprint` 从不静默降级：文件不存在、`inspect.getsource` 取不到源码、内容无法
序列化为 JSON 时都会抛 `ValueError`，而不是退回去对 `repr()` 取哈希——一个会静默
降级的指纹，比抛错更容易被误当作真实的版本证据。

::: gaia
    options:
      members:
        - fingerprint

## Tool

::: gaia
    options:
      members:
        - read_tool
        - write_tool
        - FunctionReadTool
        - FunctionWriteAdapter
        - ScenarioTools

## Model 与流式响应

`ModelProvider.generate_stream()` 返回与厂商无关的 `ModelStreamChunk`。应用可以用 `async for`
逐段消费，不需要解析 OpenAI-compatible SSE 格式。

应用代码从 `gaia` 顶层导入常用类型；只有实现自定义 Provider、Retriever 或基础设施 Adapter
时才直接依赖 `gaia.spi`。SPI 只包含协议和协议使用的数据类型，不包含具体实现。

::: gaia.spi.model
    options:
      members:
        - ModelMessage
        - ModelCallContext
        - ModelResult
        - ModelStreamChunk
        - ModelProvider

## Guardrails

Guardrail 是应用策略，不在 Gaia Core 中硬编码行业规则。`GuardedModelProvider` 可以包装任意
`ModelProvider`，分别装配输入和输出 Pipeline；同一个 Pipeline 也可用于 Retrieval 和 Tool
边界。接入顺序、失败策略和第三方适配见[安全防护](guardrails.md)。

::: gaia.spi.guardrail
    options:
      members:
        - GuardrailStage
        - GuardrailAction
        - GuardrailContext
        - GuardrailFailureMode
        - GuardrailResult
        - ContentGuardrail

::: gaia.guardrails
    options:
      members:
        - GuardrailPipeline
        - GuardrailViolation
        - GuardrailDecision
        - GuardrailDecisionSummary
        - SqlAlchemyGuardrailDecisionStore
        - PatternRule
        - PatternGuardrail
        - GuardedModelProvider

## 多 Agent Handoff

应用使用 `ScenarioResponse.handoff_to(...)` 发起 Runtime 原生移交，并在 Composition Root
注册目标 Handler 与白名单路由：

```python
async def policy_agent(context: ScenarioContext) -> ScenarioResponse:
    return ScenarioResponse.handoff_to(
        "executor",
        input=context.handoff_input,
        reason="policy check passed",
        state_updates={"policy": "least-privilege"},
    )

builder.handoffs(
    {"policy": policy_agent, "executor": executor_agent},
    routes={"scenario": ("policy",), "policy": ("executor",)},
    max_handoffs=3,
)
```

`scenario` 是入口 Scenario 的路由源。Runtime 在每次目标调用前持久化 Handoff 状态，重启后
继续；目标 Handler 仍获得同一套 Model、Retriever 和 Tool 边界，因此可以进入普通
`ScenarioResponse.propose(...)` 与 HumanGate。交接步骤和模型调用共同受 Scenario 的
`max_steps` / `max_model_calls` 限制。

::: gaia.patterns
    options:
      members:
        - AgentContext
        - AgentHandoff
        - AgentResult
        - AgentSpec
        - InMemoryHandoffOrchestrator
        - MultiAgentResult

`InMemoryHandoffOrchestrator` 是不需要持久化、工具或 HumanGate 的进程内轻量 Pattern。
旧名 `HandoffOrchestrator` 只为兼容保留。需要恢复或写操作时使用 Runtime 原生 Handoff。

## Write Tool 恢复策略

`write_tool` 要求应用明确选择外部系统真实具备的恢复能力：

- `reconcilable`：默认策略，必须提供 `reconcile`；
- `idempotent`：目标系统承诺同一幂等键可以安全重放；
- `at_most_once_manual`：不自动重放，进程在结果未确认时将命令标记为 `unknown`，交给人工处理。

`ApprovalView` 可以省略，Runtime 会根据 Tool 名称、风险和 `reason` 生成不包含业务字段的基础
确认信息；业务应用需要展示更具体且已脱敏的字段时再显式提供。

## Prompt

::: gaia.spi.prompt
    options:
      members:
        - PromptRef
        - PromptArtifact
        - PromptProvider
        - PromptRegistry

## RAG

::: gaia.spi.rag
    options:
      members:
        - DocumentSource
        - DocumentAccess
        - RetrievalRequest
        - RetrievalHit
        - Citation
        - IngestionResult

`ScenarioContext.retriever` 是绑定当前 Run 身份的检索端口。应用传入的请求不能替换租户、用户或
扩大角色；检索结果在返回 Scenario 前经过 Retrieval Guardrail。

## 应用装配与测试

`GaiaAppBuilder` 在一个 Composition Root 中注册 Scenario、Model、Retriever、Prompt、
Guardrail 和 Tool。`ScenarioTestHarness` 用相同公共端口在进程内验证读取、模型调用、动作提案、
Human Gate 和最终结果，不要求测试访问持久化表。

::: gaia.api.builder
    options:
      members:
        - GaiaAppBuilder

::: gaia.testing.scenario
    options:
      members:
        - ScenarioTestHarness
        - ScenarioHarnessResult
        - ScenarioExecutionResult

### 用 `VersionBundleGate` 给版本证据加一道 CI 闸门

`fingerprint()`（见上文 Scenario 一节）让 `rules_version` 之类的字段不再手填，但这只解决
了"版本号会不会漂移"；企业还需要一个显式的检查点来回答"这次发布，版本号是不是**按预期**
变了"——例如策略收紧后，CI 必须能确认 `policy_version` 确实变了，而不是被漏改。
`VersionBundleGate` 就是这个检查点：构造时传入 `expected: Mapping[str, str]`（`VersionBundle`
字段名到期望值），对照被测 subject 的版本证据做精确比对，任何字段不一致都会让 Gate 失败。

`GateContext` 没有单独暴露 `VersionBundle`；按照 `GaiaTestKit.run(..., subject=...)` 已有的
"subject 描述被测对象"惯例（例如现有的 `prompt_id`/`prompt_version`/`prompt_content_hash`
精确绑定模式），调用方需要把被测 Scenario 的 `VersionBundle` 字段写进 `subject`：

```python
from gaia.testing import GaiaTestKit, VersionBundleGate

report = await GaiaTestKit(
    executor,
    evaluators=(...,),
    gates=(VersionBundleGate(expected={"rules": fingerprint(rules)}), ...),
).run(dataset, subject=dict(spec.version_bundle.model_dump()))
```

`expected` 里出现的字段名会在构造时对照 `VersionBundle.model_fields` 校验；拼错字段名
（比如写成 `rule` 而不是 `rules`）会立刻抛 `ValueError`，而不是让 Gate 悄悄变成一个永远
通过的空检查。

::: gaia.testing.gates
    options:
      members:
        - VersionBundleGate
