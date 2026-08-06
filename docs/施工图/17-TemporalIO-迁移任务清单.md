# 17 Temporal IO 迁移任务清单（Gaia 受控执行层）

> **状态：迁移主体已完成。** Temporal 已是唯一持久执行 provider，SQL Runtime 已删除；
> 本文后半部分保留的 P0/P1/P2 To Do、双栈方案和迁移前风险是历史执行记录，不是当前待办。
> 当前结果以文首“目标定位”和文末“2026-07-29 收敛状态”为准。

## 目标定位（本轮结论）

- **逻辑编排**：`LangGraph` 保持场景表达与控制流（Decision/Agent/分支/并发/回放）
- **持久化执行**：`Temporal.io` 提供「可恢复长流程 + Signal/Timer + Worker 调度」
- **可观测性**：`Langfuse` 提供 Token/成本/Prompt 瀑布/Trace 追踪
- **脚手架职责**：`Gaia` 只做配置、Starter、Actuator 投影、Policy 强约束入口（不自持久化执行引擎本体）

### 这条链路对“你担心的轮子问题”的回答

- Gaia 不再把“执行编排内核”造出来：控制面仍由 LangGraph 负责控制行为表达，执行层上迁移到 Temporal 承担恢复与重放。
- 以前你担心 Gaia 会重复造“作业引擎”，现在的边界是：Gaia 是「企业生产级受控边界 + 可解释配置 + 只读证明」，Temporal 是「任务执行内核」。
- 当前状态：`runtime.execution.provider` 只接受 `temporal`，所有外部入口与审计语义保持不变。

---

## 为什么是这条链路（对照当前事实）

- Gaia 保留受控副作用、身份、策略和审计契约的**业务能力边界**。
- Temporal 已接管执行过程、长任务存活、HumanGate 等待、重试与恢复。
- Runtime SPI 现在是 Gaia API 与 Temporal adapter 之间的窄端口，不代表第二个执行引擎。

---

## 历史执行清单（已完成，保留审计轨迹）

### 0. 本轮 To Do（先读后做）

1. **定位定稿**：`runtime.execution` 是唯一执行配置入口；顶层
   `runtime.provider` 兼容入口已删除。
2. **第一跳替换**：为 `TemporalRuntimeEngine` 建立可观测迁移协议（input envelope / operation mapping）并让错误信息可追踪。
3. **单一生产路径**：声明式装配只允许 Temporal，不再提供 Persistent
   回退；无 Temporal Server/Worker 时明确失败。
4. **验证闭环**：新增至少一条单测验证迁移输入协议和失败文案。

### 本轮执行（2026-07-29 开始）

- **已完成：删除可执行 SQL Runtime**
  - 删除 `PersistentRuntimeEngine`、旧 Command/Handoff coordinator、SQL budget
    store 与 legacy test assembler。
  - controlled-task 十个验收案例改为真实 Temporal Server + Worker。
  - Activity 业务 trace 完整投影到 Workflow History，保留 actor、source refs
    与 rule refs。
  - `0015_remove_sql_runtime` 已解除观测表对 `runs` 的外键，并删除历史
    Run、event、budget、HumanGate、Command、idempotency 与 lease tables。
  - 应用自动建库不再创建 execution ledger；`run_id` 仅作为 Temporal
    correlation identifier 保留在观测记录中。
- **已完成：Run/model budget 迁入 Temporal 执行状态**
  - `RuntimeAssembler` 不再创建 `SqlAlchemyRunBudgetStore`；Activity 内
    step/model-call 预留通过 heartbeat 持久化，成功结果写回 Workflow History。
  - Handoff/Continuation 继续携带预算计数，Command Activity 由 Workflow
    调度前扣减 step；模型纠错和并发预留不能绕过上限。
- **已完成：PostgreSQL stack 删除 Runtime 身份**
  - 删除通过 `PersistentRuntimeEngine` 创建 PostgreSQL Run 的外部测试。
  - PostgreSQL 只保留 Prompt、Outbox、RAG、LangGraph checkpoint、迁移和
    观测存储职责；Run 耐久执行只由 Temporal 验收。
- **已完成：Prompt 版本固定迁到 Temporal Workflow identity**
  - 真实 Temporal Server + Worker 验证新 idempotency key 固定当前 Prompt
    release，同一 organization/key 重试返回原 Workflow snapshot 与原版本。
  - 删除 SQL Run 幂等表对 Prompt pinning 的测试所有权。
- **已完成：参考示例与生成项目直接启动 Temporal**
  - `examples/function_task` 和 `gaia init` 的 basic/approval 生成物不再
    monkeypatch SQL Runtime，真实 lifespan 中的 `app.state.runtime` 必须是
    `TemporalRuntimeEngine`。
  - 示例测试只负责声明式装配与极简 composition root；执行语义由真实
    Temporal Server + Worker 验收负责。
- **已完成：Model/Scenario Starter 契约改为 Temporal 装配**
  - 删除两个 Starter 测试对生产 `_create_runtime` 的 SQL monkeypatch。
  - 声明式组件图直接证明真实 Model Provider 被发现且 Runtime 为 Temporal；
    显式依赖优先级通过 lifespan 中的 `app.state.runtime` 验证。
- **已完成：Function Scenario API 收敛到 Temporal 装配契约**
  - 删除 `LegacyRuntimeAssembler._create_runtime` 全局 monkeypatch，以及通过
    HTTP + SQLite 重复执行 Guardrail、模型纠错和 Read Tool 的混合测试。
  - 保留三项 Gaia 胶合职责：Scenario API 产出 Temporal Runtime、重复 ID
    装配失败、Prompt release 在 Workflow 启动前解析失败。
- **已完成：Run/Gate 资源归属测试迁到 Temporal 投影边界**
  - 预置 RunSnapshot/HumanGate Query 投影，直接验证跨组织读取消、伪造审批
    都不会触发 Temporal cancel Signal 或 decision Update。
  - 删除测试中的 SQL Run/Gate、Scenario 和 Write Tool 执行链。
- **已完成：认证测试与旧执行引擎解耦**
  - API Key、AuthnProvider 和 OIDC wiring 测试只捕获进入 Temporal Runtime
    SPI 的 `RunRequest`，验证身份覆盖、冲突阻断和 trusted-service 边界。
  - 测试不再通过 `PersistentRuntimeEngine` 执行 Scenario；真实执行由 Temporal
    Server + Worker 纵向验收负责。
- **已完成：Run Listing 收敛为 Temporal Visibility 边界**
  - 删除旧 SQL Runtime 的排序、分页、过滤和游标实现测试。
  - Temporal backend 测试证明 organization、status、scenario 和 page size
    进入 Visibility 查询；HTTP 测试只验证认证范围和 opaque cursor 透传。
- **已完成：Handoff 验收迁移到 Temporal**
  - 真实 Temporal Server + Worker 测试覆盖两次 Agent Handoff、共享状态传递、
    HumanGate Update、Command Activity 和最终结果。
  - Temporal Scenario Activity 将 Handoff 识别为合法的非终态结果，交回
    Workflow History 驱动下一次 Activity，而不是误判为 Runner 失败。
  - 删除旧 SQL Runtime 的 Function Scenario、Continuation 和 Persistent
    Handoff 集成测试；Continuation 的 action result 传递由 Temporal Activity
    测试覆盖，Worker 重启恢复由真实 Temporal + LangGraph 测试覆盖。
- **已完成：第一条真实纵向切片**
  - `RuntimeAssembler` 为 Temporal 分支注入真实 `TemporalClientBackend`，不再默认报未就绪。
  - Gaia 在启动 Workflow 前执行场景准入和版本解析，继续守住 Policy 边界。
  - Temporal `gaia.runtime` Workflow 已接管 durable run ID、初始 snapshot、初始事件、
    `inspect/events_after` Query、`transition/cancel` Signal 与执行恢复。
  - Worker 使用 Temporal Python SDK 的真实 `Client.connect` / `Worker` 参数。
  - 无副作用终态 Scenario/LangGraph Runner 已通过 `gaia.runtime.run_scenario`
    Temporal Activity 执行，结果回写 Workflow snapshot。
  - Runner 内的直接 WRITE 调用仍由 `ScopedToolExecutor` 阻断；Activity 只允许写意图
    以 `SideEffectProposal` 返回，并把尚未映射的 ActionPlan/Handoff 标记为
    non-retryable。
  - 单个 `SideEffectProposal` 已在 Activity 内完成 Gaia Policy 判定，并在 Workflow
    内创建 durable HumanGate；查询使用 Query，审批使用同步 Update。
  - HumanGate 的 pending / approved / rejected / expired 状态、TTL 和重复决策结果
    已进入 Temporal Workflow history。
  - 已批准或无需审批的单个 Write Tool 直接作为 Temporal Activity 执行；
    Activity Retry Policy 由工具恢复策略和重试预算生成，不新增 Gaia Command
    轮询器、恢复循环或第二套状态存储。
  - `observability.provider=langfuse` 已提供声明式 OTLP bootstrap；同一 tracer
    同时注入 Temporal Client/Worker 与现有模型调用观测，Activity 把真实 OTel
    trace ID 回写 Run snapshot，Gaia 不保存 Langfuse Trace 副本。
  - Organization、Scenario、Run Status 已写入 Temporal Search Attributes；
    `list_runs` 从 Temporal Visibility 分页并 Query Workflow snapshot，
    `/actuator/runtime` 在 Temporal provider 下据此生成只读摘要，不双写 Run 表。
  - Agent Handoff 和单次 Write 后 Continuation 已映射为后续 Scenario Activity；
    副作用结果通过 Activity 输入回到 Runner/LangGraph，Temporal 保存调用链与重试，
    Workflow 不实现 Agent 或 Continuation 业务逻辑。
  - 模型 span 已显式映射为 Langfuse `generation`，携带 model、Token usage、
    USD cost、Prompt version 和 Run/Scenario 过滤维度；Prompt/Response 正文默认
    不上传，只保留既有哈希证据。
  - `tests/integration/test_temporal_end_to_end.py` 使用 Temporal SDK 测试 Server
    和真实 Worker 验证只读 Scenario Activity，以及
    `SideEffect -> HumanGate Update -> Command Activity -> RunSnapshot` 受控写链路，
    不经过 fake backend 或 legacy SQL Runtime；因首次运行需要下载测试 Server，
    以 `external` 标记显式执行。
  - 同一真实验收还会在 HumanGate 等待期间关闭 Worker，再由新 Worker 从
    Workflow History 重放并完成审批；Command 结果恢复进下一次 LangGraph
    StateGraph 调用，LangGraph 不使用 checkpointer，也不会重复执行已完成的图步骤。
- **本轮明确未完成**
  - 不提供 Temporal Command 查询/管理面；`RuntimeEngine.get_command` 及其
    SQL/Temporal 空壳已经删除。执行真值保留在 Temporal Workflow History 和
    Langfuse Trace，避免复制旧 Command 状态机。
  - `LangGraphScenarioRunner` 已支持“图计算一个逻辑步骤 -> Temporal 执行一个
    Command -> 把结果恢复进下一次图计算”。公开 ActionPlan 入口、调度器、恢复
    phase 和 Command 推进分支已删除；旧数据库字段只做历史快照读取。Temporal
    自定义 Search Attributes 仍需在目标集群注册。
  - Temporal 已成为唯一声明式生产 provider；Gaia 数据库和尚未迁完的
    `gaia.testing.legacy_runtime` 回归测试仍保留旧 Run/Command 写模型。
  - FastAPI 生产边界已不再 import `persistent_engine.py`；分页上限和无效游标
    语义已进入 `RuntimeEngine` SPI，Temporal Visibility 与旧回归夹具共同实现
    该契约。
  - `ScenarioTestHarness` 已停止创建 SQLite 和 `PersistentRuntimeEngine`；
    Harness 只验证一个逻辑步骤并记录 SideEffectProposal，审批、Command 执行、
    重试与恢复仅由真实 Temporal Worker 验收覆盖。
  - `RuntimeEngine.transition`、Temporal transition envelope 和 Workflow
    transition Signal 已删除；状态只允许由确定性的 Workflow/Activity、HumanGate
    Update 或 cancel Signal 推进，外部调用方不能任意写 durable status。
  - `examples/controlled_task` 的公开 ASGI 装配已改为真实
    `TemporalRuntimeEngine + TemporalClientBackend`，并删除
    `ControlledTaskComposition.create_runtime()`；尚未迁完的 SQL 行为只在
    `tests.integration.controlled_task_legacy_app` 显式装配。
  - `ReplayRunner` 已改为只接收标准 `RuntimeEngine` 工厂；生产回放通过
    Temporal Workflow，旧 `ReplayRuntimeFixture.create_runtime()` 和
    `side_effect_success_count` 专属协议已删除。
  - `/v1/diagnostics/runs/{id}/bundle` 已改为从 Runtime SPI 只读投影
    Run/Event/HumanGate，不再查询旧 SQL Run/Command 表；bundle schema 2.0
    删除 `side_effect_commands`，Command 证据指向 Temporal Workflow History。
  - `/actuator/runtime` 已删除 SQL Run/Gate/Command/Outbox 统计分支和具体
    Runtime 类型判断，统一通过 `RuntimeEngine.list_runs()` 生成只读投影；
    生产数据源即 Temporal Visibility。
  - 无调用方的 `gaia.persistence.repositories` 已整体删除，包括旧
    `CommandRepository.list_recoverable()`；Gaia 不再保留可被重新接线的
    Command recovery 仓储入口。
  - 已删除三组被真实 Temporal 验收替代的 SQL Runtime 测试：旧审批写 smoke、
    私有 CommandExecutor 幂等调用、Run/Event 表约束。对应目标证据由真实
    Server/Worker 的审批前不写、单次 Command、History 与 Worker 重启恢复提供。
  - Runtime SPI、API lifespan 和 legacy provider 的 `startup_recover`、恢复 Lease、
    批处理扫描及 Command replay 已删除；Temporal 是唯一恢复所有者。
  - Prompt 正文的显式授权捕获、成本价格表和 Langfuse Metrics/Observations
    只读聚合尚未完成；当前优先使用模型供应商返回的 Token/成本。

### 四层目标的剩余难度

| 层 | 当前状态 | 剩余难度 | 主要工作 |
|---|---|---:|---|
| Gaia 容器 | Temporal 已是默认生产 provider，Persistent 降为显式 legacy | 中 | 删除旧 Run/Command 写模型与兼容构造入口 |
| Temporal 持久执行 | Workflow/Query/Update、Command Activity、Visibility 已落地 | 中 | 目标集群注册 Search Attributes、生产部署验收 |
| LangGraph 逻辑编排 | 图状态通过 Temporal continuation 逐步推进，ActionPlan 调度器已删除 | 低 | 补充迁移示例与生产图 |
| Langfuse 可观测 | OTLP、generation、Token/成本、trace_id 已接线 | 中 | Prompt 正文授权策略、成本价格表、Metrics API 聚合 |

### 建议后续顺序

1. 删除 legacy Persistent provider 的 Run/Command 写模型与兼容构造入口。
2. 在目标 Temporal 集群注册 Gaia Search Attributes 并执行生产部署验收。
3. 按显式内容授权策略补充 Langfuse Prompt 正文和 Metrics API 只读聚合。

### 1. 统一目标锚点（先读）

1. **逻辑编排（L1）**：保留 `LangGraph` 作为上层场景编排 DSL 与图执行语义来源。
2. **持久执行（L2）**：把执行耐久化、信号、长流程恢复、Worker 调度交给 `Temporal.io`。
3. **可观测（L3）**：把 Token/成本/Prompt Trace 与 LangGraph 运行事件、Gaia 事件审计双轨融合，`Langfuse` 作为链路聚合入口。
4. **Gaia 角色（L4）**：只负责声明式配置、Starter 注入、Policy 约束、HumanGate、组织边界、Actuator 只读投影与回放/证据可见性。

### 1. P0：接口与控制面冻结（今天开始）

- **ToDo A（已完成）**：把 `runtime.execution.provider` 作为唯一配置入口。
  - 顶层 `runtime.provider` 及其 provider 解析兼容层已经删除。
  - 验收：Temporal 是唯一声明式 provider；`persistent` 配置会被严格模型拒绝。
    尚未迁完的 SQL Runtime 回归测试只能从
    `gaia.testing.legacy_runtime` 显式装配。
- **ToDo B**：给 Temporal adapter 加最小可观察性锚点（命名空间、task queue、超时、并发上限），避免无配置“黑盒失败”。
  - 迁移动作：`runtime.execution` 配置对象落到 runtime 组装入口。
  - 验收：切到 temporal 时日志/错误里可明确看到 `namespace/task_queue`。
- **ToDo C**：补齐 `RuntimeEngine` 装配边界的自动化用例。
  - 迁移动作：`assembly` 覆盖 Temporal 唯一路径，`config` 覆盖 legacy
    provider 被拒绝；旧 SQL 行为测试改从 `gaia.testing` 显式装配。
  - 验收：默认配置与显式 `runtime.execution.provider=temporal` 都构造
    `TemporalRuntimeEngine`；顶层 `runtime.provider` 被严格配置模型拒绝。

### 2. P1：Temporal 执行替换第一跳（从占位变为可接线）

- **ToDo D**：完成 Temporal 适配器“工作流启动面”与 `RuntimeOutcome` 映射的最小定义（只定义类型/协议，不实现全部行为）。
  - 产出：`RuntimeAdapterMessage`, `TemporalRuntimePlan`, 以及 `create/inspect/list_runs` 等接口的统一参数约定。
  - 验收：文档和类型签名冻结，能和当前 `ScenarioRunner` 契约对齐。
- **ToDo E**：新增 `temporal` worker 启动骨架（独立 worker/入口文件）+ 连接配置校验。
  - 验收：配置可驱动 worker 连接参数，但不要求完整端到端行为。
- **ToDo F**：在 `RuntimeAssembler` 引入 `execution` 开关并保持 `PersistentRuntimeEngine` 完全兜底。
  - 验收：同一配置默认运行路径不变；切到 temporal 后返回明确 `TemporalNotReady`，而不是静默回落。

### 3. P2：功能替换（单场景打通）

- **ToDo G**：把一个 `Decision`/`ActionPlan` 轨道映射到单一 Temporal Workflow，并回投到 Gaia 表。
- **ToDo H**：把 `Command` 与 `HumanGate` 的关键状态转换以事件快照方式写回 Gaia。
- **ToDo I**：分离 `startup_recover` 语义，Temporal 负责执行侧恢复，Gaia 负责状态一致性补齐。

### 4. P3：可观测与治理闭环

- **ToDo J**：接入 Langfuse TraceID 回传到 Gaia `RunEvent` 与 snapshot 上下文。
- **ToDo K**：把 HumanGate/SideEffect/CMD 关键节点同时显示在 Gaia 只读投影与 Langfuse Trace。

### 5. 风险（建议不跨越）

1. HumanGate/状态 CAS 与 Temporal 结果重放的一致性边界（必须先落地一次性状态真值）。
2. 幂等键与 `reconcilable/idempotent` 在 Workflow 重试下不应漂移（关键）。
3. 同时存在 `startup_recover` 与 Worker 重放时，必须定义单一“故障恢复入口”。
4. 运维链路（namespace / task queue / worker）若不标准化，迁移会被配置错误淹没。

## 历史版本 To Do

### P0（先做，最小风险）
1. **运行时契约层拆出（本轮已开始）**
   - 新建 `RuntimeEngine` Protocol（`runtime/contracts.py`）
   - API/组装层只依赖 `RuntimeEngine` 协议，不直接绑定 `PersistentRuntimeEngine`
   - `ApiDependencies`、`RuntimeAssembler`、`create_app` 保持向后兼容接口

2. **Temporal 适配器骨架（不接管全部）**
   - 新建 `src/gaia/runtime/temporal_runtime.py`
   - 定义 `TemporalRuntimeEngine(RuntimeEngine)` 的接口与 `RuntimeUnavailable` 行为（显式报“需配置 Temporal 适配器参数”）
   - 先让默认运行仍走 `PersistentRuntimeEngine`

3. **文档与决策线打通（本轮已同步）**
   - 新建本 TODO 文档（本文件）
   - 明确“Gaia 仍保留状态边界/安全边界/Actuator 投影”的不变点

### P1（第二阶段）
4. **执行轨道双栈运行（A/B）**
   - 在配置中加入 `runtime.execution`（`gaia.runtime.execution.provider`）
   - `scenario-runtime` Starter 在生命周期内根据配置注入 Runtime 实现（`persistent` / `temporal`）
   - 默认路径仍为 `persistent`，用于兼容回退

5. **Temporal 模型映射试点（单场景）**
   - `Decision`/`ActionPlan` 映射成一个或若干 Temporal Workflow
   - `Command` 与 `HumanGate` 生命周期用同一事件模型回投到 Gaia 数据库
   - 将 `startup_recover` 的职责拆分：Gaia 负责状态最终一致性，Temporal 负责执行恢复

6. **LangGraph 接口收窄为 Runner 适配层**
   - `ScenarioRunner` 仅输出“事件化动作”，不再直接承载持久态机迁移
   - 让 Temporal adapter 仅消费 `RuntimeOutcome` 与 tool proposals

### P2（稳定化）
7. **Langfuse 接入**
   - 将模型调用/工具调用 trace 统一透传到 run snapshot 中的 trace_id 链
   - 与现有观测事件互补，不替代 Gaia audit/event

8. **生产级安全与多租户对齐**
   - 组织级隔离、审批日志、write_mode、tool risk 三边界仍在 Gaia Runtime 契约层兜底
   - Temporal sidecar 仅做执行不越权，不复写身份/角色判断

---

## 历史启动记录

- 已完成：`RuntimeEngine` 契约 + API/装配层的依赖反向，`runtime.execution` 迁移入口落地。
- **本轮本地开始动作（已启动）**：
  1. 完善 `src/gaia/runtime/temporal_runtime.py` 的迁移输入协议（`build_*_envelope`）。
  2. 验证唯一入口 `runtime.execution.provider` 的装配行为，并验证已删除的
     顶层 `runtime.provider` 会被拒绝（`tests/unit/runtime/test_assembly.py` /
     `tests/unit/config/test_loader.py`）。
  3. 新增 temporal 适配器协议测试（`tests/unit/runtime/test_temporal_runtime.py`）防止无感知回退。

---

## 历史迁移难度评估（迁移前）

### 难度：高（P1/P2）

- **高**：`Runtime` 当前把“状态持久化 + 副作用 CAS + 命令恢复”与执行调度耦合。Temporal 接入不是替换一层，而是要迁移所有调用边界。
- **中**：`ScenarioRunner` 与 `SideEffectProposal` 协议本身已较清晰，作为适配层较容易落地。
- **低**：前期解耦（Protocol + 配置开关）是低风险的；真正迁移到 Temporal 的主难点在于：
  - 幂等键、HumanGate 过期、恢复语义与数据库状态机一致性映射
  - 工具执行重放与 `reconcilable/idempotent` 策略对齐
  - 与现有测试矩阵（恢复/预算/恢复租约/组织隔离）的重建

### 风险清单

1. **语义偏移**：Temporal 默认失败策略和 Gaia 的 `APPROVED -> EXECUTING` CAS 边界可能不一致，需做“结果归一化”适配。
2. **恢复语义重复**：Gaia 已有 `startup_recover`，Temporal 同时也有 replay/heartbeat/retry，需要定义单一恢复入口。
3. **运维复杂度**：新增 worker 与命名空间部署将引入调度与可观测链路运维负担。
4. **可观测一致性**：Langfuse trace 与 Gaia 事件流要能互相引用（trace_id 映射）。

---

## 历史成功标准（已被下方收敛状态取代）

- API 与组件图不变
- `runtime.scenario`、actuator、审计、HumanGate 行为在默认路径不变
- 新增配置可选择 Runtime provider（暂时 default=persistent）
- Temporal adapter 能作为第二实现运行/切换，不影响现网稳定性

---

## 2026-07-29 收敛状态

上面的“第二实现”和 `default=persistent` 是迁移启动时的历史标准，现已被
实际迁移结果取代：

- Temporal 是唯一声明式执行 provider；Gaia 不再提供可执行的 SQL Runtime。
- LangGraph 只决定逻辑步骤；Temporal Workflow/Activity 持有执行、等待、重试、
  恢复、预算与 Handoff 历史。
- HumanGate 通过 Temporal Query/Update 等待和决策，Command 通过 Activity Retry
  执行；Gaia API 只做认证、授权、策略和投影。
- `gaia worker --config ... --app module:factory` 是应用 Worker 的统一生产入口，
  与 API 复用同一个应用 composition/lifespan。
- `make demo` 依次启动本地 Temporal、应用 Worker、API 与 Console，并通过真实
  Workflow 投影播种审批、拒绝和策略拦截证据。

当前剩余工作不再是继续扩展 Runtime，而是完成最终验收并输出 Gaia 能力与边界
全景图。
