# 安全防护

Gaia 把 Guardrail 放在真实执行边界，而不是只在模型前后加一个敏感词过滤器。

## 五个防护阶段

| 阶段 | 检查对象 | 常见用途 |
| --- | --- | --- |
| `input` | 用户输入与进入模型的消息 | 注入特征、长度、PII |
| `retrieval` | RAG 检索结果 | 权限泄漏、来源与上下文污染 |
| `output` | 模型结构化结果或流式增量 | PII、内容策略、字段约束 |
| `tool_input` | 即将执行的工具参数 | 越权参数、危险操作、目标范围 |
| `tool_output` | 工具返回并进入后续流程的内容 | Secret、敏感字段、外部污染 |

每个 Guardrail 返回 `allow`、`rewrite` 或 `block`。组件自身异常不是普通的 block：
应用必须显式选择 `fail_closed` 或 `fail_open`。

## 最小用法

```python
from gaia import (
    GuardrailAction,
    GuardrailContext,
    GuardrailPipeline,
    GuardrailStage,
    PatternGuardrail,
    PatternRule,
)

pipeline = GuardrailPipeline(
    (
        PatternGuardrail(
            "secrets",
            (
                PatternRule(
                    pattern=r"token-[a-z0-9]+",
                    code="SECRET_DETECTED",
                    action=GuardrailAction.REWRITE,
                ),
            ),
            version="1.0.0",
        ),
    )
)

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

Guardrails AI 的 Validator：

```bash
uv add "gaia-framework[guardrails]"
```

```python
from gaia.integrations import GuardrailsAIValidator

validator = GuardrailsAIValidator(configured_guard)
```

这个适配器只调用 `configured_guard.validate(...)`。不要让 Guardrails AI 在适配器内自行调用
模型或 reask，否则会绕过 Gaia 的 Model Gateway、预算和调用证据。

## Provider 装饰顺序

```python
provider = InstrumentedModelProvider(
    GuardedModelProvider(
        OpenAICompatibleProvider(...),
        input_guardrails=input_pipeline,
        output_guardrails=output_pipeline,
    ),
    sink=model_invocation_sink,
)
```

外层观测可以记录模型成功、Guardrail 阻断和防护组件故障。检索与工具阶段不经过
`GuardedModelProvider`，在 Retriever 和 Tool 的调用边界直接使用 Pipeline。
