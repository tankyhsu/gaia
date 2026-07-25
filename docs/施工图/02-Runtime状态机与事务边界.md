# 02 Runtime 状态机与事务边界

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
| Workflow 节点 State/Checkpoint | LangGraph adapter | LangGraph checkpoint tables |
| 客户业务事实 | Mock/Customer source adapter | 源系统 |

LangGraph 不得直接更改 `runs`、`human_gates` 或 `side_effect_commands`。Workflow 节点通过 Runtime service 提交意图。

## 2. Run 状态转换

| 当前 | 允许下一状态 | 触发者 |
| --- | --- | --- |
| `received` | `validated`, `blocked`, `failed`, `cancelled` | Runtime |
| `validated` | `running`, `blocked`, `failed`, `cancelled` | Runtime |
| `running` | `waiting_human`, `degraded`, `blocked`, `succeeded`, `failed`, `cancelled` | Runtime |
| `waiting_human` | `running`, `blocked`, `cancelled` | Runtime after decision/expiry |
| `degraded` | none | terminal |
| `blocked` | none | terminal |
| `succeeded` | none | terminal |
| `failed` | none | terminal |
| `cancelled` | none | terminal |

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
3. commit 成功后，Workflow 调用 LangGraph `interrupt()`。
4. Checkpoint 使用 `run_id` 作为 `thread_id`。

### 4.2 决策

- 只有 `pending` Gate 可决策。
- 决策人不能等于 Run 请求者，且必须具有 `approver` 角色。
- 批准：Gate -> `approved`，Command -> `approved`，Run -> `running`，然后用 `Command(resume=...)` 恢复 LangGraph。
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
3. `unknown`：先调用 Adapter `reconcile()`，禁止盲目重试。
4. 其他状态必须是 `approved`；否则阻断。
5. 在 DB 事务中用 compare-and-set 将 `approved -> executing`，追加 event 后 commit。
6. 在事务外调用 Adapter，传入幂等键。
7. 明确成功：在 DB 事务中写入 `succeeded`、`result_ref` 和 event。
8. 明确业务失败：写入 `failed` 和 event，Run -> `blocked`。
9. 连接超时或结果不明：写入 `unknown`，调用 `reconcile()`。
10. reconcile 确认成功：转 `succeeded`；确认未执行：允许一次相同幂等键重试；仍无法确认：Run -> `blocked`，`SIDE_EFFECT_UNKNOWN`。
11. Adapter 定义漂移、构造或执行异常：Command -> `failed`，分别记录
    `TOOL_DEFINITION_MISMATCH` 或 `TOOL_ADAPTER_ERROR`，不得遗留在 `executing`。

Workflow 节点因 LangGraph 恢复而从头重跑时，必须通过 Command 幂等键读取既有结果，不得再调用 Adapter。

## 6. Checkpoint 与恢复

- LangGraph 节点只存放可序列化 State，不放 DB Session、HTTP Client、Adapter 实例或密钥。
- 节点输入使用 ID 和引用，大文本、模型输出和诊断信息通过 `input_ref/output_ref` 存储。
- Runtime 启动时扫描 `running` 和 `waiting_human` Run。
- `waiting_human` 保持等待，不自动恢复。
- `running` 从 LangGraph 最近 Checkpoint 恢复前，先处理 `executing/unknown` Command 的 reconcile。
- 找不到 Checkpoint 时 Run -> `failed`，`INTERNAL_ERROR`，不重新从头执行。

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
```

关键约束：

- `runs.run_id` primary key；
- `run_events(run_id, sequence)` unique；
- `human_gates.gate_id` primary key，每个 Command 最多一个 Gate；
- `side_effect_commands.idempotency_key` unique；
- `idempotency_records(scope, key)` unique；
- 事件和审计记录不提供 update/delete repository 方法。

## 8. 预算

P0 强制三种预算：

- `max_steps`：每进入一个 Workflow node +1；
- `max_model_calls`：每发起一次 Provider 调用 +1，包括失败调用；
- `max_duration_seconds`：从 `received_at` 到当前时间，人工等待时间不计入。

P0 记录 Token 数，但不用费用作阻断条件，因为 Mock 和客户 Endpoint 未必提供统一价格。

## 9. 不可绕过证据

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
