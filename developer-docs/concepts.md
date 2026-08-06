# 基础概念

这一页解释 Gaia 如何把一个 AI 想法组织成可运行的应用。不需要先理解框架源码；如果你只是
想尽快验证业务场景，也可以先阅读[用模板搭一个 Demo](demo.md)。

## Application

`GaiaApplication` 是应用的装配和生命周期边界。它读取 `gaia.yaml`，计算需要的组件，在进入
lifespan 后创建资源，并在退出时按相反顺序释放。

## Scenario

Scenario 描述“一次 AI 应用请求要完成什么”。普通异步函数通过 `@scenario` 声明：

- 稳定的场景 ID；
- 可用角色和工具；
- Prompt 和模型调用预算；
- 是否允许写入；
- 哪些情况需要人工确认。

Scenario 不负责创建数据库连接和模型 Client，也不能绕开统一 Temporal 执行边界。

## Starter 与 Component

Starter 是按需装配规则，Component 是装配后的具体能力。

例如选择 RAG 会展开为 PostgreSQL、Memory、pgvector、Embedding 和 RAG Pipeline。使用者通常
选择业务能力，Gaia 负责补全依赖；需要精确控制时仍可直接声明 Starter。

## Profile 与 Runtime Environment

Profile 是一组配置覆盖，例如 `dev` 或 `postgres`。Runtime Environment 是安全模式：

| Environment | 默认写入策略 | 用途 |
| --- | --- | --- |
| `mock` | 允许 | 本地确定性测试 |
| `sandbox` | 必须审批 | 联调和客户沙箱 |
| `customer` | 禁止 | 生产默认保护 |

两者相关，但不是同一个概念。

## 执行边界

所有持久 Scenario 都进入同一个 Temporal Workflow 类型，获得：

- Workflow ID、History 和 Visibility；
- Activity Retry、预算、超时和 Worker 恢复；
- Gaia Policy 与 Temporal HumanGate Update；
- Side Effect Activity 与持久化 Continuation；
- 精确版本绑定，以及 Langfuse/Actuator 关联证据。

`RuntimeEngine` 在代码中是 API 使用的窄 SPI 名称，不代表 Gaia 拥有另一套 durable runtime。

## 策略收紧覆盖（Policy Override）

`@scenario(...)` 声明的 `ExecutionPolicy`（`write_mode`、预算、`allowed_tools`）通常需要一次
代码发布才能修改。运维经常需要在不发版的情况下临时收紧某个场景——强制一次写入必须审批、
削减预算上限、或撤销某个工具的许可——`gaia.yaml` 的 `runtime.policy_overrides`（按
`scenario_id` 键入）就是为此设计的：

```yaml
runtime:
  policy_overrides:
    orders.approve_refund:
      write_mode: approval_required   # 只能比场景声明的值更严格
      max_steps: 5                    # 只能比场景声明的值更小
      deny_tools: [orders.force_refund]
```

**只能收紧，绝不能放宽。** 这不是一个随意的限制：如果一个配置文件可以放宽策略，它就变成了
绕开框架安全边界的后门——完全跳过 `@scenario` 代码本应经过的评审。因此任何字段一旦被检测到
放宽（`write_mode` 变得更宽松、预算变大、试图新增而非移除工具），`gaia.runtime.policy.
apply_policy_override` 立即抛出以 `POLICY_OVERRIDE_INVALID:` 为前缀的 `ValueError`——而且是
在应用装配阶段（`RuntimeAssembler.create_engine`，即启动期）抛出，不会等到第一个请求才失败。

**生效的收紧会体现在审计证据里，而不是悄悄发生。** 收紧生效后，Runtime 记录的
`VersionBundle.policy` 不再是 `policy-id:1.0.0`，而是 `policy-id:1.0.0+ovr.<digest>`,
其中 `<digest>` 是这次实际生效覆盖内容的确定性指纹。这意味着运维改一次 `policy_overrides` →
指纹变化 → 该时间点之后所有 Run 的审计证据都能与之前区分；如果覆盖内容和场景基线完全相同
（没有产生任何实质变化），指纹不会出现，`version` 保持不变——`+ovr.` 后缀只在真正发生了
差异时才会出现，不会成为一个"看起来权威但没有实际信息量"的标记。

## 写操作后的 Continuation

普通 Python Scenario 不会恢复已经退出的协程。需要在审批或写操作完成后根据真实结果继续判断时，
Scenario 通过 `continue_with` 指定一个命名 Handler。Runtime 持久化 Handler 和输入，写操作
成功后再把 `action_result` 交给它。Continuation 可以返回最终结果、Handoff，或提出下一项受控
写操作。

## Prompt、RAG 与 Test Kit

- Prompt 是版本化 Artifact。已发布版本不原地覆盖，Run 固定使用的精确版本。
- RAG 返回内容时同时返回 Citation，并在检索前执行租户和权限过滤。
- Test Kit 在应用外部运行 Dataset、Evaluator 和 Quality Gate，不替代生产 Runtime。

下一步：[创建第一个项目](getting-started.md)。
