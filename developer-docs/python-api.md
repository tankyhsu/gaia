# Python API

这一页从 Gaia 公开 Python 类型、函数和 docstring 自动生成。应用优先依赖 `gaia` 顶层导出的
公共 API，不要直接依赖 Runtime 或 Persistence 内部模块。

## Scenario

::: gaia.sdk.scenario
    options:
      members:
        - ScenarioContext
        - ScenarioResponse
        - ScenarioSideEffect
        - ScenarioTrace
        - ScenarioSpec
        - scenario
        - get_scenario_spec

## Tool

::: gaia.sdk.tool
    options:
      members:
        - read_tool
        - write_tool
        - FunctionReadTool
        - FunctionWriteAdapter

## Model 与流式响应

`ModelProvider.generate_stream()` 返回与厂商无关的 `ModelStreamChunk`。应用可以用 `async for`
逐段消费，不需要解析 OpenAI-compatible SSE 格式。

::: gaia.sdk.model
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

::: gaia.sdk.guardrail
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

Gaia 提供的是显式、受预算约束的 Handoff Pattern。每个 Agent 只能转交给自己的白名单目标；
达到 `max_handoffs` 后立即终止，不提供无限自治循环。

::: gaia.patterns
    options:
      members:
        - AgentContext
        - AgentHandoff
        - AgentResult
        - AgentSpec
        - HandoffOrchestrator
        - MultiAgentResult

## Prompt

::: gaia.sdk.prompt
    options:
      members:
        - PromptRef
        - PromptArtifact
        - PromptProvider
        - PromptRegistry

## RAG

::: gaia.sdk.rag
    options:
      members:
        - DocumentSource
        - DocumentAccess
        - RetrievalRequest
        - RetrievalHit
        - Citation
        - IngestionResult
