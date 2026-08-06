# 02 Runtime 状态机与事务边界

> **历史设计，已被 Temporal 执行所有权取代。** 本文描述的 `runs`、`human_gates`、
> `side_effect_commands`、`run_budgets` 和恢复事务表已由迁移
> `0015_remove_sql_runtime` 删除。当前不变量见
> [17-TemporalIO-迁移任务清单](17-TemporalIO-迁移任务清单.md)；Temporal Workflow
> History 是执行真相，Gaia 只保留业务安全契约和只读投影。

本文件定义仍然有效的受控 Runtime 不变量。M1 只改变 Provider、Workflow、Context、Tool 和 Policy
的装配来源，不降低事务、恢复、HumanGate、幂等或副作用安全要求。

## 1. 所有权

| 状态或数据 | 唯一所有者 | 存储 |
| --- | --- | --- |
| Run 生命周期 | Execution Runtime | `runs` |
| 运行事件 | Execution Runtime | `run_events` |
| Policy 决策和版本 | Execution Runtime | `runs.version_bundle` + events |
| HumanGate | Execution Runtime | `human_gates` |
| 副作用状态 | Execution Runtime | `side_effect_commands` |
| HTTP 幂等 | Execution Runtime | `idempotency_records` |
| Run 执行预算 | Execution Runtime | `run_budgets` |
| Agent Handoff 活跃状态 | Execution Runtime | `runs.handoff_json` |
| 写操作后续接状态 | Execution Runtime | `runs.continuation_json` |
| 可选 Workflow Checkpoint | Workflow adapter | Adapter 自有 checkpoint tables |
| 客户业务事实 | Mock/Customer source adapter | 源系统 |

任何 Workflow Adapter 都不得直接更改 `runs`、`run_budgets`、`human_gates` 或
`side_effect_commands`。节点通过 Runtime service 提交意图。

## 2. Run 状态转换

> **代码权威位置**：本节描述性内容与 `src/gaia/runtime/lifecycle.py` 冲突时，以代码为准。
> 该文件的四张表（`ALLOWED_TRANSITIONS`/`RunStatus`、`ALLOWED_GATE_TRANSITIONS`/`GateStatus`、
> `ALLOWED_COMMAND_TRANSITIONS`/`CommandStatus`、`ALLOWED_ACTION_TRANSITIONS`/`ActionStatus`）
> 是全部合法状态迁移的唯一事实来源；Runtime 的每一处状态写入都先经过对应的
> `validate_*_transition`（`validate_transition`/`validate_gate_transition`/
> `validate_command_transition`/`validate_action_transition`），非法迁移抛
> `InvalidStateTransition`（`code == RUNTIME_ILLEGAL_TRANSITION`）。本节和第 4/5 节的表格是
> 该权威表的可读摘要，不是第二份定义。

| 当前 | 允许下一状态 | 触发者 |
| --- | --- | --- |
| `received` | `validated`, `blocked`, `failed`, `cancelled` | Runtime |
| `validated` | `running`, `blocked`, `failed`, `cancelled` | Runtime |
| `running` | `running`, `waiting_human`, `degraded`, `blocked`, `succeeded`, `failed`, `cancelled` | Runtime |
| `waiting_human` | `running`, `blocked`, `cancelled` | Runtime after decision/expiry |
| `degraded` | none | terminal |
| `blocked` | none | terminal |
| `succeeded` | none | terminal |
| `failed` | none | terminal |
| `cancelled` | none | terminal |

`running -> running` 是一个合法的自环，不是遗漏：Run 本身没有离开 `running`，只是在其内部
推进到下一步。两个具体场景都会触发它——ActionPlan 推进到下一个动作
（`action_plan.ActionPlanManager.complete_plan_action` 的非终止分支），或者一个已就绪的
Continuation 被接续执行（`command_execution.CommandExecutor.store_command_result` /
`ActionPlanManager.complete_plan_action` 中 `continuation_json is not None` 的分支）。这两条
路径都在 `persistent_engine.py` 里以裸 `run.status = RunStatus.RUNNING.value` 写入（未经
`validate_transition`，因为旧表不允许 `RUNNING -> RUNNING`）；B1 已把该自环补进
`lifecycle.py` 的权威表，本文档此前遗漏了这一行，现已补齐。

不在表中的转换必须抛出 `InvalidStateTransition`，不得静默忽略。

每次转换在同一数据库事务中完成：

1. 校验当前状态与期望版本；
2. 更新 `runs.status` 和 `runs.updated_at`；
3. 追加对应 `RunEvent`；
4. commit；
5. commit 成功后才通知 SSE 订阅者。

## 3. 创建 Run

`POST /v1/runs` 的固定步骤：

1. 校验 `Idempotency-Key` 和 canonical request hash。
2. 已有相同键且 hash 相同：返回已有 Run，不再执行。
3. 已有相同键但 hash 不同：返回 `IDEMPOTENCY_CONFLICT`。
4. 在一个 DB 事务中创建 `idempotency_records`、`runs(received)` 和第一个 event。
5. 运行 Schema、场景、身份、Policy 和 Model capability 校验。
6. 转换为 `validated`。
7. 固定 VersionBundle。之后即使默认配置变更，该 Run 也不更换版本。
8. 转换为 `running`并启动 Workflow。
9. 同步执行到终态或 `waiting_human`后返回 201。

P0 不引入分布式任务队列。`degraded` 是“已安全结束但未完成目标”的终态，用于无可靠 Context 或模型不可用但没有产生非预期副作用的情况。

环境准入发生在创建持久化 Run 之前：`RunRequest.mode` 必须等于服务端
`runtime.environment`。场景 Policy 不匹配或请求角色不被识别时返回 403，不允许客户端选择较宽松
环境。

## 4. HumanGate

### 4.1 创建

写操作需要审批时：

1. Workflow 向 Runtime 提交 `SideEffectProposal`，不执行 Adapter。
2. Runtime 在一个 DB 事务中创建 `SideEffectCommand(status=waiting_approval)`、`HumanGate(status=pending)`、event，并将 Run 转为 `waiting_human`。
3. commit 成功后返回 `waiting_human`。可选 Workflow Adapter 再以 `run_id` 保存自己的
   checkpoint；Function Scenario 不需要额外状态机。

### 4.2 决策

- 只有 `pending` Gate 可决策。
- 决策人不能等于 Run 请求者，且必须具有 `approver` 角色。
- 批准：Gate -> `approved`，Command -> `approved`，Run -> `running`，然后由 Runtime 执行
  Command；如果 Proposal 绑定了命名 Continuation，Runtime 在成功后把 ToolResult 交给对应
  Handler。应用的 `resume` hook 只接收兼容通知，不拥有状态转换。
- 拒绝：Gate -> `rejected`，Command -> `rejected`，Run -> `blocked`，error code 为 `HUMAN_GATE_REJECTED`，不恢复 Workflow。
- 过期：在任何查询或决策前懒检查 `expires_at`。过期则 Gate -> `expired`，Command -> `rejected`，Run -> `blocked`。

## 5. 副作用事务协议

### 5.1 Safety Boundary

SideEffectProposal 不是执行授权。Runtime 必须以注册的 ToolDefinition 为事实源，校验：

- 工具已注册并位于 `allowed_tools`；
- Adapter 允许当前服务端 environment；
- 请求者具备 required roles；
- Proposal 风险与 ToolDefinition 完全一致；
- 环境 write mode 与场景 write mode 均允许执行。

环境和场景策略取更严格值。检查失败时 Run -> `blocked`，Adapter Factory 不得调用。

### 5.2 幂等键

Command 幂等键由以下字符串的 SHA-256 生成：

```text
scenario_id + workflow_version + run_id + step_id + tool_name + canonical_payload
```

`side_effect_commands.idempotency_key` 必须有唯一索引。

### 5.3 执行

1. 从 DB 加载 Command。
2. `succeeded`：直接返回之前的 `result_ref`。
3. `executing/unknown`：根据 ToolDefinition 的恢复策略处理，禁止隐式猜测。
4. 其他状态必须是 `approved`；否则阻断。
5. 在 DB 事务中用 compare-and-set 将 `approved -> executing`，追加 event 后 commit。
6. 在事务外调用 Adapter，传入幂等键。
7. 明确成功：在 DB 事务中写入 `succeeded`、`result_ref` 和 event。
8. 明确业务失败：写入 `failed` 和 event，Run -> `blocked`。
9. 连接超时或结果不明：写入 `unknown`。
10. `reconcilable` 调用 `reconcile()`；`idempotent` 在恢复时使用同一 Command Key 重放；
    `at_most_once_manual` 不重放，保持 `unknown` 并让 Run -> `blocked`,
    `SIDE_EFFECT_UNKNOWN`。
11. Adapter 定义漂移、构造或执行异常：Command -> `failed`，分别记录
    `TOOL_DEFINITION_MISMATCH` 或 `TOOL_ADAPTER_ERROR`，不得遗留在 `executing`。

Workflow 节点因恢复而从头重跑时，必须通过 Command 幂等键读取既有结果，不得盲目再次调用
Adapter。

## 6. Checkpoint 与恢复

- LangGraph 节点只存放可序列化 State，不放 DB Session、HTTP Client、Adapter 实例或密钥。
- 节点输入使用 ID 和引用，大文本、模型输出和诊断信息通过 `input_ref/output_ref` 存储。
- Runtime 启动时扫描 `running` 和 `waiting_human` Run，并确保旧 Run 有预算快照。
- `waiting_human` 保持等待，不自动恢复。
- `running` 若有 `handoff_json`，从已持久化的目标 Agent、输入、共享状态和交接次数继续。
- `running` 若有已就绪的 `continuation_json`，从命名 Handler、应用输入和 ToolResult 继续，
  不重跑入口 Scenario。
- 恢复 Agent、ActionPlan 或可选 Workflow Checkpoint 前，先处理 `executing/unknown`
  Command 的 reconcile。
- 找不到应用 Runner、Handoff Handler 或 Adapter Checkpoint 时进入稳定错误，不从入口
  Scenario 重新执行。

## 7. 数据库表

P0 必须包含以下表：

```text
runs
run_events
human_gates
side_effect_commands
idempotency_records
artifacts
replay_jobs
replay_case_results
run_budgets
```

`runs` 还必须包含 `handoff_json` 与 `continuation_json`，用于短生命周期的可恢复执行游标。

关键约束：

- `runs.run_id` primary key；
- `run_events(run_id, sequence)` unique；
- `human_gates.gate_id` primary key，每个 Command 最多一个 Gate；
- `side_effect_commands.idempotency_key` unique；
- `idempotency_records(scope, key)` unique；
- `run_budgets.run_id` primary key and foreign key to `runs`；
- 事件和审计记录不提供 update/delete repository 方法。

## 8. 预算

Runtime 强制三种持久预算：

- `max_steps`：每进入一个 Workflow node +1；
- `max_model_calls`：每发起一次 Provider 调用 +1，包括失败调用；
- `max_duration_seconds`：从 `received_at` 到当前时间，人工等待时间不计入。

P0 记录 Token 数，但不用费用作阻断条件，因为 Mock 和客户 Endpoint 未必提供统一价格。

创建 Run 时在同一事务写入 Policy 快照和计数器。Scenario/Agent 节点、Read Tool、持久化
Write Tool 在执行前原子预占 step；Provider 在发起调用前原子预占 model call，失败调用和
结构化输出纠偏同样计数。并发竞争、进程重启和 HumanGate 恢复都使用同一行，不允许重置。

## 9. Runtime 原生 Handoff

1. Scenario 或 Agent 返回 `ScenarioResponse.handoff_to(...)`。
2. Function Runner 校验目标 Handler、来源到目标的白名单和 `max_handoffs`。
3. Runtime 在调用目标 Agent 前把目标、输入、共享状态、次数和轨迹写入
   `runs.handoff_json`，追加 `agent_handoff` event。
4. 目标 Agent 作为新的执行 step 运行，可返回终态、下一次 Handoff、ActionPlan 或
   SideEffectProposal。
5. 最终 Outcome 被 Runtime 接纳后清除活跃 `handoff_json`；历史交接保留在事件链。
6. 进程在 3 和 4 之间退出时，启动恢复重新调用已记录的目标 Agent。该调用按 at-least-once
   处理，并继续消耗原 RunBudget；外部写操作仍只能经过幂等 Command。

## 10. Runtime 原生 Continuation

1. Scenario 或 Agent 通过 `ScenarioResponse.propose(..., continue_with="handler")` 把命名
   Handler 与 SideEffect/ActionPlan 绑定。
2. Runtime 在创建 Command 前将 Handler 和序列化输入写入 `runs.continuation_json`。
3. Command 或整个 ActionPlan 成功后，Runtime 把实际 ToolResult 写入该记录并标记 ready。
4. Runtime 调用应用注册的 Continuation Handler；Handler 获得
   `continuation_input`、`action_result` 以及同一套受限 Model、Retriever 和 Tool。
5. Handler 可以返回终态、Handoff、SideEffect 或 ActionPlan；所有后续动作仍进入相同 Policy、
   RunBudget、HumanGate 和审计边界。
6. 进程在 ready 后退出时，启动恢复调用命名 Handler，不恢复 Python 协程栈，也不重跑入口
   Scenario。

## 11. 不可绕过证据

`tests/architecture/` 和 `tests/integration/` 必须证明：

1. 场景包 import 具体 `WriteAdapter` 失败；
2. 未在 Runtime registry 中注册的 Tool 无法执行；
3. 未批准 Command 无法进入 `executing`；
4. 直接调用 Mock WriteAdapter 不会使 Run 成功，且客户场景代码无该引用；
5. 重启恢复后同一幂等键的 Adapter 成功计数仍为 1。
6. 请求 mode 不能覆盖服务端 environment；
7. Sandbox 的低风险写操作仍需审批；
8. Customer 默认禁写；
9. 角色、白名单、环境或风险不匹配时 Adapter 从未实例化。
10. 持久 Handoff 后重启会恢复目标 Agent，不重跑入口 Scenario，也不重置预算。
11. Handoff 目标提出高风险写操作时仍必须进入 Runtime HumanGate。
12. HumanGate 后的 ToolResult 可以驱动 Continuation 生成动态下一步，且重启后不丢失。
13. `at_most_once_manual` 的不确定写入不得自动重放；`idempotent` 只能使用原 Command Key。
