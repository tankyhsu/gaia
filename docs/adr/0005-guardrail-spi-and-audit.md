# ADR 0005：Guardrail SPI、失败语义与审计边界

状态：Accepted
日期：2026-07-24

## 背景

企业 AI 防护不是一个过滤函数。输入、检索结果、模型输出、工具参数和工具结果的风险不同，
部署环境对误拦截、漏拦截和审计失败的容忍度也不同。Gaia 需要提供统一的接入和证据边界，
但不应该把客户行业规则或某一家安全产品固化进 Core。

## 决定

Gaia Core 拥有以下稳定契约：

1. 五个执行阶段：`input`、`retrieval`、`output`、`tool_input`、`tool_output`；
2. 三种结果：`allow`、`rewrite`、`block`；
3. 明确的 `fail_closed` / `fail_open` 组件故障策略；
4. `GuardrailDecision` 证据，包含规则 ID、版本、阶段、动作、风险分、耗时和内容哈希；
5. 决策 Sink、SQLAlchemy 持久化和按 Run 查询 API。

审计记录不得保存输入、检索内容、模型正文、工具参数或脱敏前后的原文。内容关联只使用
SHA-256 引用。需要强审计的环境可以启用 `audit_required`，使审计不可用时阻断执行。

Model Provider 的推荐装饰顺序是：

```text
InstrumentedModelProvider
  └── GuardedModelProvider
        └── OpenAICompatibleProvider
```

这样输入拦截、输出拦截和防护组件故障都进入现有模型调用观测。Retrieval 与 Tool 阶段由应用
在相应执行边界调用同一个 `GuardrailPipeline`，不伪装成模型调用。

## 第三方适配

- Presidio 作为可选 PII 检测和脱敏适配器，不进入默认依赖；
- Guardrails AI 适配器只调用 `Guard.validate`。模型调用、重试、预算和观测仍由 Gaia 管理；
- NeMo Guardrails 只有在产品确实需要对话状态机时才作为外部集成评估，不进入通用 Runtime；
- LLM Guard 不作为 Starter。其上游仓库已归档，不能承担 Gaia 默认生产安全底座。

Gaia 暂不提供自动装配的第三方 Guardrail Starter。先由真实应用验证策略组合、模型资源、
延迟和误报率，再决定是否把稳定组合提升为 Starter。

## 后果

- 业务代码依赖 Gaia SPI，而不是第三方框架 API；
- 第三方组件可以替换，历史决策仍能通过 Guardrail ID 和版本解释；
- 默认安装保持轻量，`presidio` 与 `guardrails` extra 按需安装；
- Gaia 对安全执行和证据负责，但客户仍需定义行业规则、风险阈值及故障策略。
