# 安全防护

Gaia 把 Guardrail 放在真实执行边界，而不是只在模型前后加一个敏感词过滤器。

## 五个防护阶段

| 阶段 | 检查对象 | 常见用途 |
| --- | --- | --- |
| `input` | 用户输入与进入模型的消息 | 注入特征、长度、PII |
| `retrieval` | RAG 检索结果 | 权限泄漏、来源与上下文污染 |
| `output` | 模型结构化结果或完整缓冲的流式正文 | PII、内容策略、字段约束 |
| `tool_input` | 即将执行的工具参数 | 越权参数、危险操作、目标范围 |
| `tool_output` | 工具返回并进入后续流程的内容 | Secret、敏感字段、外部污染 |

每个 Guardrail 返回 `allow`、`rewrite` 或 `block`。组件自身异常不是普通的 block：
应用必须显式选择 `fail_closed` 或 `fail_open`。

## 应用装配

```python
from gaia import (
    GaiaAppBuilder,
    GuardrailAction,
    GuardrailStage,
    PatternGuardrail,
    PatternRule,
)

secrets = PatternGuardrail(
    "secrets",
    (
        PatternRule(
            pattern=r"token-[a-z0-9]+",
            code="SECRET_DETECTED",
            action=GuardrailAction.REWRITE,
        ),
    ),
    version="1.0.0",
)

dependencies = (
    GaiaAppBuilder(config)
    .scenarios(answer_question, publish_document)
    .tools(lookup_document, publish_document)
    .guardrails(
        secrets,
        stages=(
            GuardrailStage.INPUT,
            GuardrailStage.RETRIEVAL,
            GuardrailStage.OUTPUT,
            GuardrailStage.TOOL_INPUT,
            GuardrailStage.TOOL_OUTPUT,
        ),
    )
    .dependencies()
)
```

Builder 会把规则绑定到模型、Retriever、Read Tool 和持久化 Write Tool 的真实边界。
`tool_guardrails(...)` 只作为旧项目兼容入口，等价于绑定
`retrieval`、`tool_input` 和 `tool_output`，新项目应显式声明阶段。
`input` 会先检查 Scenario 的请求正文，避免危险请求先触碰 Retriever 或 Tool；进入模型前还会
再次检查完整消息，覆盖应用拼装上下文后才出现的风险。

需要在自定义组件内直接调用时，也可以使用底层 Pipeline：

```python
from gaia import GuardrailContext, GuardrailPipeline

pipeline = GuardrailPipeline((secrets,))
safe_content = await pipeline.evaluate(
    content,
    GuardrailContext(
        stage=GuardrailStage.TOOL_OUTPUT,
        run_id=run_id,
        scenario_id=scenario_id,
    ),
)
```

`PatternGuardrail` 是确定性参考实现，适合已知格式和显式规则，不等于完整的注入检测或合规
产品。

写工具有两个不同的时点：

1. `tool_input` 在创建人工审批和执行命令之前检查，审批看到的就是最终会执行的参数；
2. `tool_output` 在外部工具返回后检查，阻止不安全结果进入后续流程。

第二种阻断不能撤销已经发生的外部写入。Adapter 必须声明真实恢复策略，业务补偿由应用明确
设计，Console 会把该 Run 记为 `blocked`，而不是伪装成“没有执行”。

## 流式输出语义

没有输出 Pipeline 时，`generate_stream()` 直接转发 Provider chunk。配置输出 Guardrail 后，
Gaia 先收集完整正文，再执行一次 Pipeline；检查通过后才释放 chunk，阻断时不会先把安全前缀
发送给客户端。

这是严格安全模式，不承诺模型正文的首 Token 实时性。它避免了每个 Token 对累积全文重新执行
Presidio、正则或语义 Validator 的 `O(N²)` 开销，也避免已经发送的内容无法撤回。需要同时获得
低延迟与输出防护时，应使用具备专用增量状态接口的 Scanner；当前通用 `ContentGuardrail`
一律按完整正文处理。

## 审计决策

把 `SqlAlchemyGuardrailDecisionStore` 作为 Pipeline 的 Sink 后，每次判断会记录规则版本、
阶段、动作、风险分、耗时和内容哈希。不会保存正文：

```python
store = SqlAlchemyGuardrailDecisionStore(session_factory)
pipeline = GuardrailPipeline(guardrails, sink=store, audit_required=True)
```

运行时可以通过 `GET /v1/runs/{run_id}/guardrail-decisions` 查看汇总与逐次决策。默认
`audit_required=False`，审计故障不会影响请求；合规场景应根据客户要求显式改为强审计。

## 可选适配器

PII 检测和脱敏：

```bash
uv add "gaia-framework[presidio]"
```

```python
from gaia.integrations import PresidioGuardrail

pii = PresidioGuardrail.create_default(language="en")
```

Presidio 仍需要部署环境提供对应语言的 NLP 资源；多语言或企业自定义识别器应由应用显式创建
Analyzer/Anonymizer 后注入，不由 Gaia 隐式下载模型。

Guardrails AI 与 Hub Validator：

```bash
uv add "gaia-framework[guardrails]"
# 应用按需安装并固定自己选择的 Hub 包；Gaia 不自动发现或安装 Validator
guardrails hub install hub://guardrails/ban_list
```

```python
from guardrails import Guard
from guardrails.hub import BanList
from gaia.integrations import GuardrailsAIValidator

configured_guard = Guard(name="application-output")
configured_guard.configure(allow_metrics_collection=False)
configured_guard.use(BanList(banned_words=["internal-codename"], on_fail="noop"))
validator = GuardrailsAIValidator(
    configured_guard,
    guardrail_id="hub.guardrails.ban_list",
    version="pinned-by-application",
)
```

Gaia 兼容的是应用已经安装、实例化并配置好的 `Guard` 调用协议，不承担 Hub 目录同步、包安装、
Validator 自动发现或配置生成。应用必须把相同的 Hub 包和模型资源固定进所有实际执行 Guardrail
的 API/Worker 镜像。

Adapter 支持 Guardrails 社区常见的三类返回：通过、失败和修正后的输出。字符串输出直接进入
Gaia Pipeline；JSON 对象、数组和标量会被编码成稳定的紧凑 JSON，再作为 `rewrite` 继续执行。
同步 `validate` 会在线程中运行，异步 `validate` 会被直接等待，避免同步 Validator 占住 Gaia
的异步执行循环。

### 已验证的社区 Validator

Gaia 使用 `guardrails-ai==0.10.2` 和 Guardrails AI 官方发布的独立 Validator 包完成了真实
兼容验证。下表表示这些能力已经通过 Adapter 运行，不表示它们由 Gaia 默认安装：

| Validator | 验证版本 | 已验证行为 | Gaia 结果 |
| --- | --- | --- | --- |
| `BanList` | `guardrails-ai-ban-list==0.1.0` | 普通文本通过；拆写的 `A T H E N A` 命中禁词 | `allow` / `block` |
| `ValidJson` | `guardrails-ai-valid-json==0.1.0` | 合法 HR JSON 通过；尾逗号非法 JSON 被拒绝 | `allow` / `block` |
| `DetectPII` | `guardrails-ai-detect-pii==0.0.6` | `GuardrailContext.metadata` 把检查对象从邮箱覆盖为电话号码，并匿名化号码 | `rewrite` |

`DetectPII` 的 metadata 验证等价于：

```python
from gaia import GuardrailAction, GuardrailContext, GuardrailStage
from guardrails_ai.detect_pii import DetectPII

configured_guard.use(
    DetectPII(
        pii_entities=["EMAIL_ADDRESS"],
        on_fail="fix",
        use_local=True,
    )
)
validator = GuardrailsAIValidator(configured_guard)

result = await validator.evaluate(
    "Call me at 212-555-1234",
    GuardrailContext(
        stage=GuardrailStage.INPUT,
        run_id="run-123",
        scenario_id="hr-onboarding",
        metadata={"pii_entities": ["PHONE_NUMBER"]},
    ),
)
# result.action == GuardrailAction.REWRITE
# result.content == "Call me at <PHONE_NUMBER>"
```

Hub CLI 安装需要有效的 Guardrails Hub token。官方独立发行包也可以由应用自己的包管理器安装，
此时导入路径形如 `from guardrails_ai.detect_pii import DetectPII`，而不是
`from guardrails.hub import DetectPII`；两种方式最终都把配置好的 `Guard` 交给同一个 Gaia
Adapter，兼容语义不依赖导入路径。

`DetectPII` 默认可以使用 Hub 远程推理，这需要 Hub 凭证。使用 `use_local=True` 时需要
Presidio、NLP 资源和对应语言模型；当前英文实现会使用约 400 MB 的 `en_core_web_lg`。生产镜像
应在构建阶段固定并预装这些资源，不应让 API/Worker 在处理请求时临时下载。

### 运行时 metadata

需要 `sources`、`query_function`、PII 实体或应用上下文的 Hub Validator 可以直接使用
Guardrails 的 `metadata` 约定：

```python
from gaia.integrations import GuardrailsAIValidator

validator = GuardrailsAIValidator(
    configured_guard,
    metadata={"sources": policy_chunks},
    metadata_factory=lambda content, context: {
        "tenant_id": context.scenario_id,
        "content_length": len(content),
    },
)
```

每次执行时，Adapter 按以下顺序合并 metadata，后者覆盖前者：

1. 构造 Adapter 时提供的静态 `metadata`；
2. 当前 `GuardrailContext.metadata`；
3. 同步或异步 `metadata_factory(content, context)` 的返回值。

因此应用既可以固定向量函数或可信来源，也可以由 Retriever、Tool 或自定义 Pipeline 在每次
运行时传入数据。Gaia 不猜测某个 Validator 需要哪些键；缺少必需 metadata 时按 Guardrail
执行异常进入 Pipeline 的 `fail_closed` 或 `fail_open` 策略。

### `on_fail` 与外部调用边界

推荐使用 `on_fail="noop"`，让失败结果回到 Gaia，由 Pipeline 统一转换成阻断与审计决策。
Guardrails 的本地 `fix` 通过后，修正输出会被映射为 Gaia `rewrite`；`noop`、`filter` 或
`refrain` 的失败结果会被规范化为 Gaia `block`，`exception` 会被视为 Guardrail 执行异常。
返回 `reask` 的结果不会在 Adapter 内继续调用模型，而会以 `GUARDRAILS_AI_REASK_REQUIRED`
阻断；只有应用同时声明 `correctable=True` 并配置 Gaia 有限纠偏时，才由 Gaia 发起受预算和证据
约束的新模型调用。

内置 LLM、远程 API 或大模型推理的 Hub Validator 在调用协议上同样可以运行，但其内部调用是
应用选择的外部黑盒依赖：不会自动经过 Gaia Model Gateway，也不计入 Gaia 模型预算或模型调用
证据。应用需要显式管理凭证、数据出境、超时、重试、资源和版本。要求这些调用也受 Gaia
模型治理时，应使用应用自有的 `ContentGuardrail`/Provider 适配实现，而不能启用 Hub 内部的
`reask` 或 `fix_reask`。

## 有限纠偏

结构化输出的格式错误与安全阻断不是一类问题。Gaia 默认不自动重试；应用确认模型调用预算
足够后，可以只为可修复输出开启一次或少量纠偏：

```python
dependencies = (
    GaiaAppBuilder(config)
    .scenarios(answer_question)
    .model(model_provider)
    .guardrails(output_validator, stages=(GuardrailStage.OUTPUT,))
    .structured_output_correction(max_attempts=1)
    .dependencies()
)
```

可纠偏范围只有：

- Pydantic 输出 Schema 不匹配，例如遗漏必填字段或字段类型错误；
- `GuardrailResult(action="block", correctable=True, ...)` 的输出 Validator。

Guardrails AI Adapter 需要应用明确声明该 Validator 只做可修复的结构/业务字段校验：

```python
validator = GuardrailsAIValidator(configured_guard, correctable=True)
```

Prompt 注入、PII、敏感主题、工具越权、Guardrail 自身异常和审计不可用均不可纠偏。它们直接
阻断，不能用 reask 绕过。每次纠偏都重新经过 Model Gateway，生成独立调用证据并消耗
`max_model_calls`；额度不足返回 `BUDGET_EXCEEDED`，尝试耗尽返回
`MODEL_OUTPUT_INVALID`。纠偏消息只包含 Validator ID、错误码和 Schema 字段，不回填被阻断
正文。

## Provider 装饰顺序

```python
provider = GuardedModelProvider(
    BudgetedModelProvider(
        InstrumentedModelProvider(
            OpenAICompatibleProvider(...),
            sink=model_invocation_sink,
        ),
        run_budget_store,
    ),
    input_guardrails=input_pipeline,
    output_guardrails=output_pipeline,
)
```

外层 Guardrail 先检查输入，之后 Budgeted Provider 原子预占调用额度，再由 Instrumented
Provider 记录真实调用。因此输入阻断不消耗调用额度，Provider 失败和输出纠偏都会消耗。模型实际返回后
才检查输出，因此输出阻断仍保留一次成功的 Provider 调用证据，并另外记录 Guardrail 决策。
检索与工具阶段不经过 `GuardedModelProvider`，由 Builder 在 Retriever 和 Tool 边界装配。
