# ADR 0001：ScenarioRunner 是唯一 Runtime 扩展边界

- 状态：部分被 Temporal 迁移取代
- 日期：2026-07-23

> `ScenarioRunner` 作为逻辑编排窄端口的决定仍然有效；本文关于
> `PersistentRuntimeEngine` 持有状态、恢复和副作用所有权的决定已被
> [Temporal 迁移任务清单](../施工图/17-TemporalIO-迁移任务清单.md)取代。

## 背景

Gaia 同时需要支持简单 Python 函数和复杂状态机，但它们必须共享准入、幂等、预算、HumanGate、
副作用控制和审计语义。历史 `WorkflowPort` 没有接入 Runtime，与实际使用的 `ScenarioRunner`
形成了两个含义重叠的入口。

## 决定

`PersistentRuntimeEngine` 只依赖 `ScenarioRunner`。`@scenario` 生成不可变 `ScenarioSpec`，
`FunctionScenarioRunner` 将普通异步函数适配到这个 SPI；LangGraph 及未来引擎也只能在同一边界
接入。删除未使用的 `WorkflowPort`，Runtime 代码不得 import 具体 Workflow 引擎。

装饰器只声明元数据，不执行网络、文件、数据库 I/O，不创建 application-scoped 资源，也不写入
全局注册表。

## 后果

轻量场景不需要 LangGraph，但不存在第二套轻量 Runtime。复杂引擎必须满足同一组契约测试，
不能改变 Gaia 对状态和副作用的所有权。
