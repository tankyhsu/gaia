# 开发者指南

Gaia 负责把模型、Prompt、知识、流程和工具装配成一个可运行、可检查、可测试的企业 AI 应用。
它不重新实现模型 SDK、数据库或工作流引擎，而是在这些能力之上提供一致的工程边界。

## 一次请求如何经过 Gaia

```text
请求
  -> Scenario
  -> Runtime
  -> Prompt / Context / Model / Tool
  -> Policy 与 HumanGate
  -> 结果、事件和调用证据
```

所有执行路径共享 Run、幂等、预算、恢复、审计和安全策略。简单函数、Pipeline 或 LangGraph
不会因为实现方式不同而绕开这些约束。

## Gaia 提供的框架能力

- `gaia.yaml`、Profile、Starter 和自动装配；
- 应用生命周期与资源管理；
- Run、幂等、预算、恢复和审计；
- Policy、HumanGate 与外部写入保护；
- 五阶段 Guardrail、无正文安全决策证据和可选第三方适配；
- Prompt 版本、RAG 引用和模型调用证据；
- Test Kit、诊断、Actuator 和 Dev Console。

## 推荐阅读顺序

1. 阅读[内部机制](mechanisms.md)，理解配置、装配、Runtime 和安全边界。
2. 阅读[安全防护](guardrails.md)，理解五个检查边界和失败策略。
3. 阅读[基础概念](concepts.md)，认识代码中使用的核心对象。
4. 按[创建第一个项目](getting-started.md)跑通开发环境。
5. 使用[命令行参考](cli.md)创建流程、检查配置和诊断依赖。
6. 扩展框架时查看 [Python API](python-api.md)和 [HTTP API](http-api.md)。

如果你接手的是业务构建者已经验证过的 Demo，先确认他的样本、判断标准和待接入资源，再决定
需要激活哪些 Starter 或实现哪些项目级 Adapter。
