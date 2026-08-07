# 为什么需要 Gaia 这一层

> 一个常见问题：我已经在用 LangGraph 做编排，也接了 Temporal 做持久化，为什么还需要 Gaia？
>
> 这篇文章用三个具体场景回答这个问题。结论先放：**LangGraph 解决"怎么走下一步"，Temporal 解决"任务别丢"，但"谁能让它做、做之前要不要批准、做完能不能证明"这一层，两个都不管。** Gaia 就是补这一层。

## 问题不在"能不能做"，在"做了之后能不能证明"

绝大多数 Agent 框架的宣传话术都集中在"能不能"——能不能调工具、能不能多步推理、能不能记住上下文。这些能力 LangGraph、AutoGen、CrewAI 都做得不错。

但企业落地时的真实问题不是"能不能"，是**"做了之后"**：

- AI 改了一笔订单，事后审计问"当时谁授权的、用的什么规则、Prompt 是哪个版本"，能不能回答？
- 审批要等三天，进程重启了，AI 还能不能从中断点继续，而不是把订单改两次？
- 同一个 Run，三个月后能不能还原当时的版本、决定和工具调用？

这些问题 LangGraph 不管——它只管 State 和节点路由。Temporal 也不管——它只管 Workflow History 和 Activity 重试。**中间这一层"受控执行 + 可追溯证据"是空的，需要每个项目自己实现，而大多数项目实现得不对。**

下面三个场景具体说明。

## 场景一：高风险写入的事前审批

### 业务

客服 Agent 处理用户退款请求。Agent 识别意图、查询订单、判断金额、调用 `issue_refund` 工具。退款涉及资金出账，必须由有权限的审批人确认后才能执行。

### LangGraph + Temporal 手搓版

```python
# LangGraph 节点
async def maybe_refund(state):
    if state["amount"] > 100:
        state["pending_approval"] = True
        # 怎么"暂停"等审批？
        # 方案 A: 在节点里 await 一个外部 signal —— 阻塞 Worker，不安全
        # 方案 B: 把状态写库，外层轮询 —— 重新发明 Temporal
        # 方案 C: 用 Temporal Signal/Update —— 正确，但要在 Graph 外再套一层
    else:
        await call_refund_api(state)
    return state
```

正确方案是 C，但实际写出来你会发现：

1. **LangGraph 的 State 和 Temporal 的 Workflow History 是两套状态**，谁主谁从？怎么同步？
2. **审批决策的可信来源**：审批接口收到 "approved" 后，怎么确认是审批人本人？怎么确认审批的是这一次 Run 的这一次副作用，而不是另一次？
3. **副作用执行前的最后一道闸**：审批通过后，谁检查"工具白名单、风险等级、当前用户角色、环境写入模式"都还成立？审批到执行之间用户角色被吊销了怎么办？
4. **拒绝证据**：被拒绝的 Run 留下什么？只记一条日志，还是结构化证据（谁拒的、拒的哪个动作、当时策略快照）？

这四件事，**每一件都是控制层的事，不是编排层的事**。把它们写进 LangGraph 节点里，节点就开始变重、变脆、变难测试；把它们散落到 Temporal Activity 里，又失去了"统一控制边界"。

### Gaia 版

```python
@write_tool(
    "support.issue_refund",
    risk_level=RiskLevel.HIGH,
    reconcile=_reconcile_refund,
)
async def issue_refund(ticket_id: str, amount: float, *, idempotency_key: str):
    ...

@scenario(
    "support.request_refund",
    allowed_tools=("support.issue_refund",),
    write_mode=WriteMode.ENABLED,
    rules_version=fingerprint(tools),
)
async def request_refund(context: ScenarioContext) -> ScenarioResponse:
    return ScenarioResponse.propose(
        ScenarioSideEffect(
            tool_name="support.issue_refund",
            payload={"ticket_id": context.text, "amount": ...},
            risk_level=RiskLevel.HIGH,
            approval_view=ApprovalView(title="Approve refund", ...),
        ),
        pending_result={"status": "pending_refund"},
    )
```

业务代码只声明"我想做这件事，它是 HIGH 风险"。剩下的事 Gaia 接管：

- 工具准入：`allowed_tools` 白名单 + 风险等级 + 角色匹配
- 暂停等待：Run 进入 `waiting_human` 状态，**工具未执行**
- 审批可信：HumanGate 决策带 `decided_by` + `roles` + `comment`，绑定具体 Run 和具体 SideEffect
- 执行前再检查：审批通过后、工具执行前，策略再次评估（角色可能已被吊销）
- 拒绝证据：被拒绝的 Run 留下结构化 Gate 证据，不是日志行

**关键差异**：手搓版的控制逻辑散落在 Graph 节点和 Activity 里，Gaia 版的控制逻辑是声明式的、集中的、可测试的。

## 场景二：崩溃恢复与幂等

### 业务

新员工入职流程 Agent：创建邮箱、开通代码仓库权限、注册 ERP 账号、发放设备。一个 Run 跨越四个系统，每个系统都可能暂时不可用。Worker 在第二步完成后崩溃重启。

### LangGraph + Temporal 手搓版

LangGraph 的 Checkpointer 能存 State，但**它不存"外部副作用到底做没做"**。重启后：

```python
async def create_repo(state):
    # 重启后这一步会不会重跑？
    # 如果重跑，会不会创建两个仓库？
    # 如果不重跑，怎么知道上次到底成功了没？
    repo = await github.create_repo(state["employee"])
    state["repo_created"] = True  # 这个 True 是崩溃前写的还是崩溃后写的？
    return state
```

正确解法是每个外部写入都用幂等键 + reconcile 回查。但 LangGraph 不管这个——它只存 State，不管 State 里的 `repo_created` 这个 bool 是不是真的对应一个已存在的仓库。你要自己：

1. 给每个外部调用生成稳定幂等键（Run ID + step ID）
2. 实现 reconcile 函数（崩溃后调外部 API 确认）
3. 在 Activity 里处理"已 done / 未 done / 不确定"三态
4. 把三态结果映射回 LangGraph State

这套逻辑每个项目都要重写一遍，且极易写错。最常见的错误是**把"调用成功"和"副作用生效"混为一谈**——HTTP 200 不代表对方真的处理了。

### Gaia 版

```python
@write_tool(
    "hr.create_repo",
    risk_level=RiskLevel.MEDIUM,
    reconcile=_reconcile_repo,  # 崩溃后调这个确认
)
async def create_repo(employee_id: str, *, idempotency_key: str):
    return await github.create_repo(employee_id, idempotency_key=idempotency_key)
```

Gaia 的 Runtime 在崩溃重启后：

1. 从 Temporal Workflow History 找到未完成的 Activity
2. 调用 `reconcile(idempotency_key=...)` 回查外部系统
3. reconcile 返回结果 → 视为已完成，不重放
4. reconcile 返回 `None` → 视为未完成，安全重放（幂等键保证不会双写）
5. 不支持幂等的老系统 → 声明 `AT_MOST_ONCE_MANUAL`，阻断交人工，**不自动重放不确定写入**

**关键差异**：手搓版把"外部副作用状态"和"LangGraph State"混在一起，Gaia 版明确区分——State 是编排层的，副作用状态由 `reconcile` 从外部系统权威查询。

## 场景三：版本固定与审计还原

### 业务

三个月前 AI 拒绝了一笔贷款申请，客户投诉。审计人员要还原当时的执行：用的什么 Prompt、什么策略版本、模型是哪个、工具定义是哪个版本。

### LangGraph + Temporal 手搓版

- Prompt 改了？通常没存历史版本，或存了但没绑定到具体 Run。
- 策略改了？策略代码在 Git 里，但当时跑的是哪个 commit？没人记得。
- 模型换了？模型 ID 当时记在哪了？日志里？日志还在吗？
- 工具定义改了？工具签名变了，但当时调用的是旧签名，能还原吗？

最常见的结果是：**"当时大概是这样"**。审计人员拿不到证据，只能信。

### Gaia 版

Run 创建时 Gaia 固定一个 `VersionBundle`：

```
VersionBundle:
  policy:        策略版本
  workflow:      Workflow 定义版本
  rules:         rules_version（来自 fingerprint(tools)）
  prompt:        prompt_id + 精确版本 + 内容哈希
  model_profile: 模型配置版本
  toolset:       工具集版本
  context_profile: 上下文配置版本
```

每个字段都是不可变引用。三个月后审计：

- Prompt → 从 Prompt Registry 取回当时版本的精确内容（含哈希校验）
- 策略 → 当时策略版本快照
- 模型 → 当时模型配置
- 工具调用 → 存的是 `input_ref` / `output_ref` 哈希引用，可验证 payload 完整性

`rules_version=fingerprint(tools)` 这个设计专门防一种事故：**有人偷偷把 `risk_level` 从 `HIGH` 改成 `LOW`**。手写 `rules_version="1.0.0"` 会在弱化风险后继续撒谎说"还是 1.0.0"；`fingerprint(tools)` 会自动变，新 Run 用新指纹，旧 Run 仍固定旧指纹，审计证据不会撒谎。

**关键差异**：手搓版的"版本"是 Git commit + 日志 + 记忆，Gaia 版的版本是 Run 创建时固化的不可变结构化证据。

## 这一层为什么没人做

不是没人想做，是难做对。它要求同时理解三件事：

1. **企业控制语义**——身份、组织、角色、风险等级、写入模式、审批策略。这些是 IdP / 审批系统 / 合规审计的领域，不是 AI 框架的领域。
2. **分布式系统正确性**——幂等、reconcile、至少一次/至多一次、崩溃恢复。这是 Temporal / Saga / Outbox 的领域。
3. **AI 应用的特殊性**——非确定性输出、Prompt 版本、模型版本、上下文窗口、Guardrails。这是 LLM 框架的领域。

这三者交集很小，做这个交集的人更少。所以市面上的框架要么只做编排（LangGraph），要么只做耐久（Temporal），要么只做 AI（LangChain/LlamaIndex），**中间这一层"AI 应用的受控执行"几乎没人认真做**。

Gaia 就是做这一层。

## 什么时候不需要 Gaia

诚实地说，多数 AI 应用不需要 Gaia：

- **无副作用问答 / RAG / 聊天机器人** → 直接调模型 API + 任意向量库
- **内部 PoC / Demo / Hackathon** → LangChain + Streamlit 更快
- **只有低风险写操作 + 不需要审计** → 自己包一层 try/except 够用
- **没有合规 / 审计 / 故障恢复硬约束** → 用 Gaia 是过度工程

Gaia 的价值随以下四个维度上升：

```
价值 ∝ 写操作风险 × 审批需求 × 故障恢复需求 × 审计需求
```

四个维度都高 → Gaia 解决的是真问题，自己实现要几个月且极易出错。
四个维度都低 → 用 Gaia 是杀鸡用牛刀。

## 判断清单

以下问题中有两个以上回答"是"，Gaia 通常值得评估：

- AI 会执行写操作（退款、改订单、改权限、改合同），而不只是回答问题？
- 某些动作必须在执行前由人确认，且确认必须可信（不是前端按钮）？
- 一次任务会跨越多个外部系统，可能等待、重试、跨进程或跨天？
- 不同组织或用户只能查看和操作自己的执行记录？
- 失败后需要从中断点恢复，而不是从头再来（且不能双写）？
- 审计、合规或运维人员需要看到可验证的执行证据，而不是日志行？
- Prompt / 策略 / 模型会随时间迭代，但旧 Run 的结果必须可按当时版本解释？

## 下一步

- 看具体业务如何映射到框架：[从三个 Case 理解 Gaia](try-it.md)
- 运行起来看受控执行的三种终态：[运行起来](getting-started.md)
- 理解模块边界与责任划分：[Gaia 全景图](architecture.md)
- 开始写自己的受控场景：[开发者指南](developer-guide.md)
