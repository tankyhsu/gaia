# 内部机制

本页解释 Gaia 如何把 LangGraph、生产必需的 Temporal.io 和 Langfuse 接成受控执行链。先建立整体
直觉请读[架构全景图](architecture.md)。

## 配置与自动装配

`GaiaApplication.from_config()` 读取 `gaia.yaml`，按以下顺序合并配置：

1. 框架默认值；
2. Starter defaults；
3. YAML；
4. active Profile；
5. 环境变量；
6. CLI `--set` 覆盖。

配置模型是严格的。未知字段和已删除的顶层 `runtime.provider` 都会在启动前失败。
`runtime.execution` 只选择执行后端。开发、测试和单机 PoC 可以使用 in-process：

```yaml
gaia:
  runtime:
    execution:
      provider: in_process
```

多副本、跨服务或要求故障接管时必须使用 Temporal：

```yaml
gaia:
  runtime:
    execution:
      provider: temporal
      server_address: temporal.example.internal:7233
      namespace: customer-a
      task_queue: customer-a-agent
      tls_enabled: true
```

customer 生产环境强制 Temporal，否则应用会在启动前失败。API/Worker 副本数、HPA、跨可用区
调度等物理拓扑由 Helm/Kubernetes 配置，不在应用配置里重复声明。LangGraph
Checkpointer 保存图状态；Gaia audit projection 保存长期证据；Temporal 负责分布式执行所有权、
消息、重试、等待和恢复。这三个职责不能相互冒充。

Starter 只声明组件及依赖，不在 import 时创建连接。进入 application lifespan 后，
`GaiaApplicationContext` 才包含真实资源；退出时按反向顺序关闭。

## in-process 与 Temporal 共用一套应用装配

in-process 模式只用于非生产环境：启动 API 进程，Scenario 在请求进程内运行，并将终态 Run 与事件写入 Gaia 审计库。
它不启动 Worker，也不接受 HumanGate、SideEffect 或 Handoff 的耐久语义。

API 和 Worker 不允许分别手工拼依赖：

```bash
gaia dev --config gaia.yaml --app my_app.app:create_app
gaia worker --config gaia.yaml --app my_app.app:create_app
```

`gaia worker` 导入 application factory，进入它的 lifespan，读取
`app.state.runtime` 中的 `TemporalRuntimeEngine`，再注册同一 composition 提供的
Scenario 和 Command Activities。这样配置、Policy、Tool Registry、Model 和客户 Adapter
不会在两个进程里形成两套不一致的影子装配。

## 一次 Run 的持久执行

### 1. API 边界

创建 Run 前，Gaia API 完成：

- 认证凭据解析；
- 请求身份和服务端身份一致性；
- organization 资源所有权；
- Run mode 与部署 environment 一致性；
- 请求契约和幂等指纹归一化。

通过后，API 用 `TemporalClientBackend` 启动固定的 Gaia Workflow 类型。Workflow ID 是
持久 Run 标识；重复 ID 与不一致请求由 Temporal/请求指纹边界拒绝。

### 2. Workflow 边界

`GaiaRuntimeWorkflow` 持有：

- 当前 Run snapshot；
- 单调事件序号；
- step/model/tool 预算；
- HumanGate 等待状态；
- Command Activity retry 配置；
- Handoff 与 Continuation；
- terminal outcome。

这些字段进入 Workflow History。Worker 重启后由 Temporal replay 恢复，不需要 Gaia
数据库扫描器、恢复租约或后台 Command runner。

### 3. Scenario Activity

Workflow 调用 Scenario Activity。Activity 从应用装配中找到目标 `ScenarioRunner`：

- 普通 `@scenario` 由 `FunctionScenarioRunner` 适配；
- LangGraph 应用由 `LangGraphScenarioRunner` 适配；
- 两者都返回同一个 `RuntimeOutcome` 契约。

Runner 可以完成、阻断、提出 HumanGate、提出 SideEffectProposal 或 Handoff，但它不直接
改变 Workflow 状态。Workflow 解释结果并决定下一次 durable transition。

## LangGraph 的准确边界

LangGraph 拥有 State、节点、条件边和“下一步做什么”。`LangGraphScenarioRunner` 每次只推进
一个可持久化逻辑步骤，并把结果转回 `RuntimeOutcome`。

LangGraph 不拥有：

- Workflow ID 和 History；
- HumanGate 的长时间等待；
- Command Activity Retry；
- Worker 崩溃恢复；
- Temporal Search Attributes。

因此应用可以自由修改图结构，而不需要重新实现 durable runtime。

## HumanGate

写入需要审批时，Workflow 保存 Gate snapshot 并进入 `waiting_human`：

- API/Console 通过 Temporal Query 读取 Gate；
- 决策接口先做认证、organization ownership 和 approver role 校验；
- 校验通过后通过 Temporal Update 提交 `approved` 或 `rejected`；
- Workflow History 保存决定者、角色、comment、规则引用和时间；
- approved 才继续 Command Activity，rejected 进入 blocked。

API 不写 `human_gates` 表，也不能在 Temporal 之外推进 Gate。

## Side Effect 与 Command Activity

Scenario 只能提出 `SideEffectProposal`。Activity 创建前 Gaia 检查：

- 工具是否注册；
- Scenario 是否允许该工具；
- 调用者是否具有 required roles；
- risk level 与 write mode 是否允许；
- 当前 Adapter definition 是否与 Scenario 绑定版本一致；
- 环境是否允许真实客户写入。

验证后，Temporal 执行 Command Activity。`reconcilable`、`idempotent` 和
`at_most_once_manual` 是 Gaia 的业务恢复契约；重试次数、backoff、heartbeat 和执行恢复由
Temporal Activity 机制承担。

## Handoff 与 Continuation

`@scenario(allowed_handoffs=...)` 显式声明可达目标。装配阶段验证目标存在和边合法性；
Workflow 把 Handoff payload、预算和当前版本证据带入后续 Scenario Activity。

Continuation 同样由 Workflow History 持久化：写 Activity 完成后，Temporal 继续调用声明的
handler。Gaia 不保存另一份 handoff/continuation SQL 状态。

`InMemoryHandoffOrchestrator` 位于 `gaia.patterns`，只是无持久化、无 HumanGate 的进程内
协作 Pattern，不是生产受控执行入口。

## 预算与超时

Run、model、tool 和 Command step 的计数由 Workflow payload 和 Activity heartbeat 传递：

- Workflow 在调度 Command 前预留 step；
- Activity 在模型或工具工作前预留对应预算并 heartbeat；
- Activity 成功后把计数返回 Workflow History；
- Handoff 和 Continuation 继承计数；
- 未配置的可选预算表示不限制，不会误判为零预算。

Gaia operational database 不保存 `run_budgets` 表。

## 可观测性

Langfuse 通过 OpenTelemetry 接入：

- Temporal Client/Worker interceptor 建立 Workflow 与 Activity spans；
- Model instrumentation 记录 model、usage、cost、retry 和错误；
- `langfuse.session.id` 使用 Temporal run ID；
- Prompt version 和 scenario ID 作为安全属性传递；
- Prompt/response 正文默认不进入 Gaia SQL 观察证据。

Langfuse 是 Trace、Token、成本和 Prompt 瀑布的所有者。Gaia observability stores 只保存
无正文、可关联的业务证据，不尝试复制完整 Trace backend。

## 只读投影

API 和 Actuator 不拥有执行状态，但 Gaia **拥有证据**：

- 单 Run 状态来自 Temporal Query；Temporal 说这个 Workflow 已经不存在时，回落到审计投影；
- 事件与 Gate 同理：先 Query，读不到就读审计投影；
- **Run 列表只来自审计投影**。它一度走 Temporal Visibility，代价是每行要发一次 Workflow
  Query 回源、Worker 全下线时列表不可用、保留期之后返回空——现在有一条测试专门禁止这条路
  再被接回去；
- `/actuator/runtime` 汇总运行信息，但没有写接口；
- 诊断包导出相同只读证据。

### 审计投影：证据比执行活得久

Temporal 按 namespace 保留期删除 Workflow History。执行真相可以被删——它的用途是重放；
证据不能，它的用途是事后回答。所以 `GaiaRuntimeWorkflow` 在证据每次变化时调用
`gaia.runtime.record_audit`，写进 `audit_runs` / `audit_run_events` / `audit_human_gates`。

三条刻意的设计：

- **不是只在终态写一次**：一个等在人工审批上的 Run 可能停留一整个 TTL，这段时间它也必须
  是可查的。
- **写不进去就不算跑完**：Activity 无限重试，证据落库失败的 Run 不进入终态。
- **投影不能授予批准**：`record` 可以记录 Gate、记录拒绝与过期（只会收回权限），但永远
  不能把 Gate 变成 `approved`。只有认证过的 API 路径能。`execute_command` 写入前查这条
  记录，对不上就 `GATE_DECISION_UNVERIFIED`。这样一来，能连上 Temporal namespace 不等于
  拥有批准权。

PostgreSQL/SQLite 中 observation 表的 `run_id` 是外部关联字符串；`audit_*` 表则是 Run 在
Temporal 之外的持久记录。

## Prompt、RAG、Memory 与 Outbox

这些属于应用数据，不属于 durable execution：

- Prompt Registry 可以使用文件或 PostgreSQL；
- LangGraph Checkpoint 可以使用 memory、SQLite 或 PostgreSQL；
- 长期 Memory 和 pgvector RAG 使用独立 store；
- Outbox 使用数据库事务和行级领取保证至少一次发布。

它们可以与 Temporal run ID 关联，但不能推进 Workflow 状态。

## 安全边界

Gaia 能强制：

- 服务端认证身份优先于请求体自报身份；
- organization ownership；
- monotonic policy override 只能收紧；
- tool allow/deny、roles、risk、write mode；
- Adapter definition drift 在执行前失败；
- SecretRef 不进入 Actuator 和诊断输出。

Gaia 不能替代：

- Temporal namespace、Worker 容量和灾备治理；
- 客户 Adapter 自身的幂等和对账能力；
- 企业 IdP 的身份生命周期；
- 任意代码执行 Sandbox；
- 正式合规认证。

## 失败时看哪里

| 症状 | 首要证据 |
| --- | --- |
| Workflow 未启动 | Gaia API 日志、Temporal namespace/address |
| 一直处于 running | task queue 是否有匹配的 `gaia worker` |
| Activity 重试 | Temporal Workflow History |
| 等待审批 | Gate Query、approver authorization、Update History |
| 模型成本异常 | Langfuse session/trace |
| 工具被阻断 | Gaia rule refs、Guardrail/Policy evidence |
| 单条 Run 与执行不一致 | 先看 Temporal Query，再核对 Gaia 审计投影和投影写入 Activity |
| Run 列表缺失或筛选异常 | Gaia 审计投影；列表不读取 Temporal Visibility |

原则是：逻辑问题看 LangGraph，执行问题看 Temporal，观测问题看 Langfuse，装配和策略问题看
Gaia。不要用新增 Gaia 状态机来掩盖上游系统的职责。
