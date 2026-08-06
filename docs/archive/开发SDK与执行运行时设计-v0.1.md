# 开发 SDK 与执行运行时设计 v0.1

## 1. 为什么要增加这一层

现有 Gaia 已经定义 Agent Harness、Workflow、Context 和场景包，但这些更接近“能力模块”。如果没有统一执行内核，每个场景仍会各自处理权限、状态、超时、人工审批、幂等、恢复和审计，最终只能复用目录，不能复用行为。

本设计增加两个正交的工程层：

- **开发 SDK**：抽象开发一个企业 AI 场景时反复使用的能力；
- **执行运行时**：在业务运行时强制执行边界，让业务结果按照预期产生。

它们不是第四、第五类业务场景。Agent、Workflow、Context 仍是三类落地能力；SDK 与 Runtime 是承载这些能力的工程底座。

## 2. 总体分层

```text
客户入口 / 成熟 Agent 工作台 / 最小业务 UI
                    │
          场景应用与客户规则层
        （由应用提供的已确认任务）
                    │
              Developer SDK
  RunSession / Model / Tool / Context / Workflow / Event
                    │
            Execution Runtime
 Policy / State / Human Gate / Budget / Side Effect / Audit
                    │
        Integrations / Application Adapters
 成熟基础设施绑定 / 身份 / 客户源系统
```

依赖只能向下。场景可以依赖 SDK，SDK 不能依赖具体场景或 Integration；成熟基础设施 Client
通过 Integration 接入，客户写系统通过 Application Adapter 接入。所有高风险外部调用必须经过
Runtime，场景不得直接绕过授权边界。

## 3. 开发 SDK 的最小表面

### 3.1 RunSession

持有一次运行所需的短期上下文：

- `run_id`、`scenario_id` 和运行档位；
- 用户身份、组织和角色；
- 当前业务实体引用；
- 当前步骤、短期状态和 Checkpoint；
- 固定的模型、Prompt、规则、工具和流程版本。

它不是通用长期记忆。跨会话经验必须经过 Context 的治理流程后才能发布。

### 3.2 ModelGateway

- 通过统一接口使用云端、客户平台、本地推理服务或 Mock；
- 统一文本和结构化输出；
- 记录 Provider、Endpoint、模型制品版本、参数、Token、耗时和错误；
- 在启动或接入时探测结构化输出、Tool Calling、Streaming 和上下文上限；
- 接受 Runtime 分配的预算和超时；
- 支持真实 Provider 与 Deterministic Mock；
- 不负责业务规则和最终授权。

首版只做 Provider 适配、能力探测和可用性降级，不建设复杂模型调度平台。本地模型服务对它只是一个 Endpoint；GPU、权重、量化、SFT 和 LoRA 生命周期不进入 Gaia 核心。

### 3.3 Tool

每个工具必须声明：

- 输入和输出 Schema；
- 只读或写入；
- 风险等级和所需角色；
- 超时、重试和幂等策略；
- Mock / Sandbox / Customer Adapter；
- 可产生的副作用与补偿入口。

工具实现不自行决定是否允许执行；Runtime 根据声明和策略做最终裁决。

### 3.4 ContextProvider

统一返回 `ContextEnvelope`，屏蔽文档检索、结构化查询和客户已有知识平台的差异。Context 实现负责来源、权限、版本、新鲜度与缺口，SDK 只定义消费契约。

### 3.5 Workflow

提供 `start / suspend / resume / cancel / inspect` 等最小生命周期接口。LangGraph 是首版实现选择，但场景代码不应直接依赖其内部对象跨模块传递。

### 3.6 Agent Bridge

把成熟 Agent 工作台或 Lite 入口转换为统一 `RunRequest`，并把工具、Context 和 Workflow 暴露给入口。首版不提供通用多 Agent 通信；需要协作时先通过显式 Workflow 和事件完成。

### 3.7 Cache、RateLimiter 与 EventPublisher

- `CacheProvider` 提供带 namespace 和 TTL 的临时字节缓存，不承担持久事实；
- `RateLimiter` 返回额度、剩余量和 retry-after，首个 Redis 实现使用原子固定窗口；
- `EventPublisher` 隔离进程内 Handler 与未来 MQ Adapter；
- PostgreSQL Transactional Outbox 保证业务记录和待发布事件同一事务提交；
- 投递语义是至少一次，Consumer 必须幂等。

Redis、Outbox 与 Publisher 都是可选能力，不进入每次 Run 的强制主链。

## 4. 执行运行时的职责

### 4.1 Run 生命周期

```text
received → validated → running → waiting_human
                     ↘ degraded
                     ↘ blocked
                     ↘ failed
waiting_human → running → succeeded | failed | cancelled
```

P0 中 `degraded`、`blocked`、`succeeded`、`failed` 和 `cancelled` 是终态。完整转换表以[施工图](../施工图/02-Runtime状态机与事务边界.md)为准。

状态变化只能由 Runtime 完成，并写入不可缺失的运行事件。

### 4.2 Policy Enforcement

策略分三层：

1. 平台底线：身份、审计、幂等、高风险审批等不可关闭；
2. 场景围栏：金额阈值、允许步骤、可用工具和失败转人工条件；
3. 环境策略：Mock、Sandbox、Customer 各自允许的读写范围。

策略必须版本化，并与每次 Run 绑定。Prompt 不得承担 Policy 的职责。

服务端 `runtime.environment` 是环境安全事实，不能由 `RunRequest.mode` 切换。副作用执行前必须以
注册的 ToolDefinition 为准校验工具白名单、角色、风险、允许环境与有效 write mode；场景或模型
提交的 Proposal 不能降低工具风险。

### 4.3 State 与恢复

- 每个关键步骤前后保存 Checkpoint；
- 需要跨边界发布的事件先与业务状态一起写入 Outbox；
- Runtime 重启后可从最近安全点恢复；
- 人工等待不占用模型或进程资源；
- 恢复前检查配置、权限和业务实体是否仍然有效；
- 已确认的副作用不能因重放而重复执行。

### 4.4 Side-effect Boundary

所有写操作先形成 `SideEffectCommand`：

```yaml
command_id: string
run_id: string
tool_name: string
idempotency_key: string
risk_level: low | medium | high
approval_ref: string | null
payload_ref: string
status: proposed | approved | executing | succeeded | failed | compensated
```

> 上述仅为早期形状示意。P0 的权威字段和状态集以 `specs/openapi.json#/components/schemas/SideEffectCommand` 为准，P0 不实现补偿流程。

Runtime 在真正提交前检查权限、Policy、审批、幂等和当前源系统状态。场景或模型不能直接调用写入 Adapter。

### 4.5 Sandbox 边界

当前 Sandbox 是集成测试环境，不是任意代码执行容器：

- Mock：无外部客户资源；
- Sandbox：测试凭据、脱敏数据、测试 Endpoint，所有写操作默认审批；
- Customer：真实资源，默认禁写并要求显式开启。

Adapter 必须声明允许的 environment；配置错误在应用启动时失败。容器隔离不能替代凭据、Endpoint
与 Runtime Policy 隔离。只有未来加入 ReAct、Shell、动态代码或开放式插件时才建设 Code Execution
Sandbox。

### 4.6 预算与韧性

- 模型调用次数、Token、费用和总耗时上限；
- 工具级超时、有限重试和退避；
- 外部系统熔断和降级；
- 低置信、数据过期、权限不足和多次失败时转人工；
- 失败分类必须区分模型、Context、规则、工具、系统和人工等待。

### 4.7 运行证据

每次 Run 必须保留：

- 使用的代码、配置、模型、Prompt、规则、Context 和工具版本；
- 每步输入输出引用与责任主体；
- Policy 判定、人工动作和副作用状态；
- 最终业务结果、失败类型和评估结果。

可观测性不是只看技术指标，而是回答“业务为什么这样执行、是否符合预期”。

## 5. 通用受控任务的围栏

| 阶段 | 围栏 | 失败处理 |
| --- | --- | --- |
| 意图与补充信息 | 必要业务字段不全时不得进入后续处理 | 继续询问或转人工 |
| 事实读取 | 身份与业务实体可见范围校验通过 | 拒绝并记录权限事件 |
| 依据检索 | 必须有来源、有效版本和适用范围 | 拒绝自动判断，转人工 |
| 规则判断 | 硬条件只由版本化规则计算 | 规则缺失时阻断 |
| 高风险动作 | 超阈值、异常或高风险操作必须审批 | 等待人工，不自动继续 |
| 系统写入 | 必须有幂等键和当前状态复核 | 超时后查状态，禁止盲重试 |
| 结束 | 审计证据完整且业务结果可确认 | 标记不完整，不伪报成功 |

固定测试样本必须逐条证明这些围栏真的生效。

## 6. 与当前模块的关系

- `src/gaia/sdk/`：公共 Model、Workflow、Context、Tool、Event、Cache 与 RateLimiter 契约；
- `src/gaia/runtime/`：Run 生命周期、Policy、HumanGate、副作用、恢复和安全边界；
- `src/gaia/integrations/`：成熟基础设施 Client 的生命周期绑定；
- `src/gaia/capabilities/`：组合多个端口与 Integration 的可选能力；
- `src/gaia/application/` 与 `src/gaia/starters/`：声明式装配、资源作用域和组件图；
- `examples/controlled_task/`：客户应用如何提供场景、规则和 Adapter 的参考实现，不进入框架包。

## 7. 首版 Scope

首版只为 `controlled-task` 合成参考流实现：

- 一个 RunSession；
- 一个模型 Gateway；
- 一个 ContextProvider；
- 三至五个 Tool；
- 一个确定性 Workflow；
- 一个 Human Gate；
- 一个 Side-effect Boundary；
- 一套事件、回放和围栏测试。

首版明确不做：多 Agent 通信总线、通用任务调度平台、插件市场、多租户管理平台、复杂模型路由和
独立微服务拆分。当前已提供 PostgreSQL long-term memory、Redis Cache/RateLimiter 和 Outbox，
但它们仍是可选 Provider，不改变 Runtime 核心边界。

## 8. 抽象与发布门槛

开发顺序不是“先把所有模块抽象完，再写业务”，而是：

1. 写出黄金场景和业务不变量；
2. 跑通一次完整执行；
3. 把重复且稳定的调用抽为 SDK；
4. 把不可绕过的检查收口为 Runtime；
5. 用第二个场景验证抽象；
6. 接口至少经历两个场景后，才考虑独立版本和发布 SDK。

这样既吸收开发框架的复用优势，也把 AI 应用最重要的“业务按预期运行”放在中心。
