# ADR 0006：生产强制 Temporal，in-process Runtime 仅服务开发

## 状态

Accepted — 2026-08-02

## 背景

Gaia 的产品定位是运行在 Helm/Kubernetes 上的企业级分布式 Agent Runtime，而不是面向简单应用的
轻量框架。生产流程需要跨副本任务所有权、跨进程消息、Timer、Activity Retry、Worker 故障接管和
Workflow Replay，这些能力由 Temporal 提供。

本地开发和自动化测试仍需要更短的反馈路径。LangGraph Checkpointer 可以保存图状态，Gaia 审计
投影可以保存 Run 与事件证据，但二者都不能替代 Temporal 对生产分布式执行的所有权与恢复能力。

## 决策

`runtime.execution` 支持两个 Provider，但它们不是两个同等级的生产选项：

- `in_process`：mock 开发默认值，仅用于开发、测试和单机 PoC。
  Scenario 在 API 进程内完成，Gaia 将终态 Run 和事件写入审计投影。它不是生产部署选项。
- `temporal`：Gaia 唯一的生产 Runtime。所有 customer 环境必须
  使用 Temporal，由其拥有执行历史与恢复；Gaia 审计投影继续提供长期、统一的证据查询。

任何不是 Temporal 的 customer 配置都会在严格配置校验阶段失败。in-process Runtime 遇到
SideEffect、Handoff 或需要跨请求继续的结果时，以 `DURABLE_EXECUTION_REQUIRED` 阻断，不执行
副作用，也不静默降级。

## 部署边界

| 场景 | in-process | Temporal |
| --- | --- | --- |
| 本地开发、自动化测试、单机 PoC | 默认 | 可选 |
| customer 生产环境 | 禁止 | 必须 |
| Helm/Kubernetes、多 API/Worker 副本 | 禁止 | 必须 |
| HumanGate、跨分钟/跨天等待 | 禁止 | 必须 |
| 关键写入、可恢复重试、补偿 | 禁止 | 必须 |
| Workflow Replay 与 Worker 版本固定 | 不提供 | 必须 |

## 后果

Gaia 的公共 API、策略、身份、审计投影和 Console 不因 Provider 改变。执行语义由统一
`RuntimeEngine` 协议隔离；`RuntimeAssembler` 先组装公共业务依赖，再选择开发期 in-process 或生产
Temporal 适配器。生产 Helm 和 production-shaped Compose Profile 显式选择 Temporal；副本与调度
完全由部署层负责。生成项目只在 mock 开发 Profile 使用 in-process，customer Profile 显式启用 Temporal，
审批应用从开发期就显式启用 Temporal。
