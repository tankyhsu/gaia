# ADR 0003：GaiaApplication 是逻辑部署单元

- 状态：已接受
- 日期：2026-07-23

## 决定

一个 `GaiaApplication` 可以注册多个相关 Scenario，并部署多个共享持久化层的副本。Gaia 不强制
每个 Scenario 一个微服务，也不建设企业级分布式 Scenario 注册中心。

应用按业务限界上下文、数据与权限边界、安全等级、外部依赖、容量、可用性、发布周期和团队所有权
拆分。多个应用通过 API Gateway、事件总线或外部业务编排协作。

## 后果

Scenario 共享应用级模型网关、持久化和基础设施资源，同时保有独立的 Prompt、Policy、
VersionBundle 和测试集。部署边界由业务与运行约束决定，而不是由装饰器或工作流数量决定。
