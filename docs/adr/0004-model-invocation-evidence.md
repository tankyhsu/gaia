# ADR 0004：模型观测记录工程证据

- 状态：已接受
- 日期：2026-07-23

## 决定

统一模型调用记录使用 `ModelInvocation` 和 `ModelUsage`。证据关联 Run、Scenario、Provider、
模型、参数哈希、Prompt 版本及内容哈希、请求与响应安全引用、Token、延迟、重试、错误和可选成本。

默认不记录 Secret、完整敏感 Prompt、客户原始数据或模型私有思维链。请求与响应默认保存受控引用
或哈希，明文采样必须由应用显式配置并遵循数据策略。

## 后果

M3 的 Provider Wrapper 和可选 OpenTelemetry Integration 共享同一契约。观测失败不得改变业务
Run 结果；未启用外部观测系统时 Gaia 不引入强制依赖。
