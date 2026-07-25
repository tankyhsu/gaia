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

Scenario 不负责创建数据库连接和模型 Client，也不能绕开统一 Runtime。

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

## Runtime

所有 Scenario 都进入同一套 Runtime，获得：

- Run 和事件记录；
- Idempotency-Key；
- 预算和超时；
- Policy 和 HumanGate；
- Side Effect 执行与恢复；
- 精确版本绑定和可观测证据。

## Prompt、RAG 与 Test Kit

- Prompt 是版本化 Artifact。已发布版本不原地覆盖，Run 固定使用的精确版本。
- RAG 返回内容时同时返回 Citation，并在检索前执行租户和权限过滤。
- Test Kit 在应用外部运行 Dataset、Evaluator 和 Quality Gate，不替代生产 Runtime。

下一步：[创建第一个项目](getting-started.md)。
