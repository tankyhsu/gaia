# 第一次接触 Gaia

Gaia 帮你构建一种**会调用工具、会改变业务数据，但不会失去控制的 AI 应用**。

它不是大模型，也不是替你画流程图的工具。你把模型、业务函数和外部系统接进来，Gaia 负责让每一次执行都经过身份、权限、策略、人工确认和审计，并在等待或故障后继续运行。

Gaia 面向构建和交付这类应用的开发者、平台工程师与 FDE。它提供框架、Runtime 和开发工具，不直接提供面向业务人员的产品界面或无代码搭建能力。

如果你只记住一句话：

> 普通 Agent 关注“把事情做完”，Gaia 还要回答“谁让它做、为什么允许、做到哪一步、出了问题能否继续、事后能否证明”。

## 先用一个场景理解它

假设员工让 AI 发布一份客户报告：

1. AI 查询客户和报告内容。这是读取，通常可以直接执行。
2. AI 判断需要调用 `publish_report`。这是写操作，可能影响客户。
3. Gaia 检查当前用户、允许使用的工具和风险策略。
4. 高风险写操作暂停，等待有权限的人查看具体动作并批准。
5. 批准后继续执行；拒绝则停止，不会绕过审批。
6. 整条链路留下可查询的状态、审批和工具证据。

<div class="gaia-step-flow" role="img" aria-label="一次受控业务动作的六个步骤">
  <div class="gaia-step"><span>01</span><strong>用户目标</strong><small>提出要完成的业务任务</small></div>
  <div class="gaia-step"><span>02</span><strong>决定下一步</strong><small>模型或业务逻辑选择动作</small></div>
  <div class="gaia-step gaia-step--control"><span>03</span><strong>Gaia 控制检查</strong><small>身份、策略、风险与工具准入</small></div>
  <div class="gaia-step"><span>04</span><strong>执行或等待</strong><small>低风险执行，高风险等待审批</small></div>
  <div class="gaia-step"><span>05</span><strong>业务结果</strong><small>完成、受控拒绝或明确失败</small></div>
  <div class="gaia-step gaia-step--evidence"><span>06</span><strong>证据落地</strong><small>状态、决定与工具结果可查询</small></div>
</div>

## Gaia 能做什么

| 你遇到的问题 | Gaia 提供的能力 |
| --- | --- |
| Agent 运行到一半，进程重启了 | 持久执行、恢复、重试和运行预算 |
| 高风险工具不能自动调用 | 工具准入、风险策略和执行前审批 |
| 审批等待几小时或几天 | 暂停 Run，收到可信决定后继续 |
| 多租户用户不能互相查看 Run | 认证、组织归属和资源访问控制 |
| 出问题后说不清发生了什么 | Run、事件、Gate、工具和模型证据 |
| 需要观察成本和模型行为 | 接入 tracing、token、成本和 prompt 观测 |
| 本地能跑，生产不知道怎么部署 | API、Worker、数据库和生产化验收路径 |

## Gaia 不替你做什么

Gaia 不会替你定义业务规则，不会自动知道哪个员工能退款，也不会替代 CRM、ERP、知识库或订单数据库。它也不保证模型永远判断正确。

你仍然需要提供：

- **业务事实**：客户、订单、库存等真实数据来自你的系统。
- **业务动作**：查询、发布、退款等工具由你的适配器实现。
- **业务规则**：谁能做什么、风险多高、何时需要审批。
- **模型与提示词**：如何理解目标、如何选择下一步。
- **验收标准**：什么算成功，哪些失败必须被阻止。

Gaia 提供的是这些部件之间的受控运行底座。

## 推荐学习顺序

### 我想先看具体行为

从 [三个 Case](try-it.md) 开始，把请假办理、权限开通和制度问答映射到 Gaia 的场景、策略、Gate、工具和证据。

### 我要先把它运行起来

进入 [20 分钟走通 Gaia](getting-started.md)，运行参考环境并检查三种受控结果。
如果你在区分 `make demo`、日常开发、`dev-full`、Compose 验收和 Helm 生产，先看
[选择运行与部署方式](runtime-profiles.md)。

### 我要开始写代码

继续读 [开发者指南](developer-guide.md)，再打开仓库中的
`examples/function_task/README.md`。

### 我需要理解系统边界

读 [Gaia 全景图](architecture.md)。它解释 Gaia、模型、Temporal、LangGraph、PostgreSQL 和外部业务系统各自负责什么。

### 我要排障或审计

进入 [核心概念](concepts.md)、[运行机制](mechanisms.md) 和 [HTTP API](http-api.md)。这些是进阶参考，不是入门前置知识。

## 判断 Gaia 是否适合你的项目

以下问题中有两个以上回答“是”，Gaia 通常值得考虑：

- AI 会执行写操作，而不只是回答问题吗？
- 某些动作必须在执行前由人确认吗？
- 一次任务会等待、重试、跨进程或跨天吗？
- 不同组织或用户只能查看自己的执行记录吗？
- 失败后需要恢复，而不是从头再来吗？
- 审计人员需要看到可验证的执行证据吗？

如果你的需求只是一次无副作用的模型问答，直接调用模型 API 往往更简单。
