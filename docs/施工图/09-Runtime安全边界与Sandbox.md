# 09 Runtime 安全边界与 Sandbox

## 1. 结论

Gaia 当前实现的是 **Runtime Safety Boundary + Integration Sandbox Profile**，不是任意代码执行
沙箱。没有 ReAct、Code Interpreter、Shell 或浏览器自由执行能力时，不建设容器级 Sandbox 平台。

三类能力必须分开：

| 能力 | 解决的问题 | 当前状态 |
| --- | --- | --- |
| Runtime Safety Boundary | 一次工具调用能否执行 | 已实现，所有环境强制 |
| Integration Sandbox | 执行后最多能影响哪些测试资源 | 已实现配置与 Adapter 环境绑定 |
| Code Execution Sandbox | 任意代码、Shell、文件和网络隔离 | 未实现，当前非目标 |

容器隔离不能替代 Runtime Policy。一个容器如果持有生产 Token，仍然可以修改真实 ERP 或数据库。

## 2. 服务端环境是唯一事实

`runtime.environment` 由服务端 `gaia.yaml`、Profile、环境变量或 CLI 覆盖决定：

```yaml
gaia:
  profile: mock
  runtime:
    environment: mock
  profiles:
    sandbox:
      runtime:
        environment: sandbox
        write_mode: approval_required
    customer:
      runtime:
        environment: customer
        write_mode: disabled
```

`RunRequest.mode` 暂时为兼容性保留，但只作为客户端声明。它必须等于服务端环境，否则在创建 Run
之前返回 `ENVIRONMENT_MODE_MISMATCH`。调用者不能通过把请求写成 `mock` 或 `sandbox` 改变实际
Adapter、凭据或安全策略。

## 3. 环境写入上限

未显式配置 `runtime.write_mode` 时使用以下安全默认值：

| Environment | 默认写入上限 | 含义 |
| --- | --- | --- |
| `mock` | `enabled` | 只允许声明支持 mock 的 Adapter；仍受场景 Policy 和风险规则约束 |
| `sandbox` | `approval_required` | 所有写操作必须 HumanGate；禁止配置为无人审批的 `enabled` |
| `customer` | `disabled` | 默认禁止真实写入，必须由部署配置显式开启 |

最终写入策略取环境上限与场景 `ExecutionPolicy.write_mode` 中更严格的一项。场景只能收紧环境
策略，不能放宽。

## 4. 副作用执行前的固定校验

Workflow 只能产生 `SideEffectProposal`。Runtime 在建立 Command 或调用 Adapter 前依次验证：

1. Runner 的 `ExecutionPolicy.scenario_id` 与请求场景一致；
2. 用户角色属于场景 Policy 的可识别范围；
3. 工具已经显式注册；
4. 工具位于 `ExecutionPolicy.allowed_tools`；
5. 注册的 `ToolDefinition.kind` 是 `write`；
6. 当前服务端环境位于 `ToolDefinition.allowed_environments`；
7. 用户具备 `ToolDefinition.required_roles`；
8. Proposal 风险等级与注册定义完全一致，Workflow 或模型不能降低风险；
9. 环境与场景的有效 `write_mode` 允许写入；
10. 根据有效写入模式和风险决定直接执行或创建 HumanGate。

任一检查失败，Run 进入 `blocked`，写 Adapter 不会实例化。

## 5. Tool 注册是安全边界

写工具必须同时注册定义和 Factory：

```python
WriteToolRegistration(
    definition=ToolDefinition(
        name="update-record",
        version="1.0.0",
        kind="write",
        risk_level="high",
        required_roles=["operator"],
        timeout_seconds=5,
        max_retries=0,
        idempotent=True,
        allowed_environments=["sandbox"],
    ),
    factory=create_sandbox_adapter,
)
```

Factory 返回的 Adapter 定义必须与注册定义完全一致，否则命令失败为
`TOOL_DEFINITION_MISMATCH`。这防止配置审查的是低风险工具，运行时却替换成另一个实现。

应用启动时会检查所有已注册写 Adapter 是否允许当前环境。Sandbox 进程误装 Customer Adapter
或反向误装时，启动立即失败，不等待首次请求。

## 6. Integration Sandbox 的实际隔离

Gaia Core 能强制 Adapter 环境绑定，但以下资源隔离由应用和部署 Profile 提供：

- 独立数据库、Schema、Bucket 或 Namespace；
- 脱敏或合成数据；
- 测试账号、最小权限凭据和独立 SecretRef；
- 客户测试 Endpoint 或 Mock 写 Adapter；
- 出站网络 allowlist；
- 独立模型 Token、调用次数、时间和费用预算。

首个参考应用的 Sandbox 使用真实 Runtime、Policy、HumanGate、数据库和事件链，但写 Adapter 仍
只修改内存 Mock 资源。它证明装配与围栏，不声称模拟了客户网络。

## 7. Adapter 调用与恢复

通过安全校验后，写操作仍必须遵守：

- Command 状态机与数据库 CAS；
- 确定性幂等键；
- 审批与请求者分离；
- Adapter 超时后的 reconcile；
- `executing/unknown` 启动恢复；
- Adapter 构造或执行异常转成 `TOOL_ADAPTER_ERROR`，不得遗留为假成功。

HumanGate 是授权环节，不是隔离环境。审批通过后 Adapter 会真实执行，因此环境和凭据隔离仍是
必要的第二道防线。

`executing/unknown` 启动恢复本身还有两条边界（D1/D1.1，详见 developer-docs/mechanisms.md）：

- 恢复由跨副本租约保证同一时刻只有一个副本在跑，按固定批大小分页并用游标推进，避免单个
  永远失败的记录挡住其它可恢复记录，也避免恢复任务本身把应用启动卡死；
- 每种写恢复策略只有有限次自动重试预算（`at_most_once_manual` 为零次），预算耗尽后 Command
  进入终态 `needs_attention`，不再参与后续恢复。**这只是一个不可自动恢复的标记，不是处置
  入口**：框架不提供把 `needs_attention` 改回其它状态的 API。人工处置意味着有人在下游系统
  核对真实结果后修改 Gaia 的权威记录，这需要独立的授权模型和审计链路，本次不做，Dev Console
  也不能替这件事背书。

## 8. 与 Test Kit 的关系

Gaia Test Kit 可以用同一 Dataset 驱动不同环境：

```text
mock      -> 快速、确定性、无外部资源
sandbox   -> 真实模型/数据库/测试系统的集成测试
customer  -> 少量、显式授权的验收测试
```

Test Kit 决定测什么和如何判断；Runtime Environment 决定被测应用能触碰什么。两者不是两套
Runtime，也不是同一个 Profile。

## 9. 后续触发 Code Execution Sandbox 的条件

只有加入下列能力之一时才单独设计执行沙箱：

- 模型生成并运行 Python、JavaScript 或 Shell；
- ReAct Agent 自主选择开放式工具；
- 文件上传后的动态解析或不可信代码；
- 浏览器自动化访问未知站点；
- 用户自定义插件在进程内执行。

届时需要进程/容器隔离、只读文件系统、网络策略、资源配额、超时销毁和制品扫描。该能力应作为
独立 Starter 或服务，不进入当前 Runtime 的默认依赖。

## 10. 部署拓扑边界（D2）

生产执行只有一档：**Temporal Server + Gaia Worker**。Workflow History、任务重放、
长流程等待、跨副本调度和 Worker 故障恢复均由 Temporal 提供；Gaia API 启动时不扫描
Run、不抢恢复租约，也不重放 Command。

- **SQLite**：仅用于本地配置、审计和开发数据，不是 Workflow History，也不具备 Run
  恢复语义。
- **PostgreSQL**：承载 Gaia 的配置、Prompt/RAG、审计等应用数据，不是 Workflow
  History，也不参与生产 Run 调度。
- **Outbox dispatcher 天然多副本安全**，但机制与上面的命名租约不同：它对每一条待发布
  事件单独做行级租约（`locked_by`/`locked_until` 字段，PostgreSQL 上配合
  `SELECT ... FOR UPDATE SKIP LOCKED`），多个副本可以同时调用
  `OutboxDispatcher.dispatch_once()` 而不会重复领取同一条事件。默认
  `batch_size=50`、`lease_seconds=30`、`max_attempts=8`、`retry_delay_seconds=5`
  （`gaia.yaml` 的 `outbox.*` 配置项）。

跨副本 Run 协调只由 Temporal task queue、Workflow ID 和 Workflow History 提供；Gaia
配置模型不存在 legacy Persistent provider。

## 11. 认证边界（E3）

`gaia.sdk.auth.AuthnProvider` 是身份解析的唯一入口，三种结果互不混淆：抛
`AuthenticationError` 拒绝请求（401）；返回 `UserIdentity` 时它是唯一事实源，
覆盖 `RunRequest.user`，与请求体不一致就拒绝（`IDENTITY_MISMATCH`）而不是静默
覆盖；返回 `None` 表示可信服务调用，`RunRequest.user` 按请求体生效。

默认实现 `ApiKeyAuthnProvider` 只认证调用方服务，不认证它代为执行的终端用户：
**Key 校验通过后，Gaia 不对 `RunRequest.user`（包括其中的 `roles`，直接参与
`validate_roles` 和工具 `required_roles` 校验）做任何交叉核验，调用方自己
对这个字段的真实性负全责**——这是已知边界，不是缺陷，口吻与第 1 节和第 10 节
一致：没有做到端到端身份认证，就不假装做到。需要端到端身份认证的部署必须提供
自己的 `AuthnProvider` 并返回 `UserIdentity`。完整契约见
`developer-docs/http-api.md`「认证：`AuthnProvider`」一节；本任务（E3）只交付
SPI 契约和这一个默认实现，不实现 SSO、OIDC 或 mTLS。

## 12. 资源归属与审批人身份（F1，安全修复）

**背景**：第 11 节定下的"认证身份是唯一事实源"规则最初只在 `create_run`
落地——`api/app.py` 的 `authorize()` 只返回错误、丢弃了 `authenticate()`
解析出的身份，Run 读取/取消、Gate 读取/审批等接口都只判断了"是否认证成功"，
没有判断"认证成功的是谁"。结果是一个与目标资源无关的认证调用方，能读取
甚至审批不属于自己组织的 Run/Gate，且 Gate 审批人身份完全由请求体的
`decided_by` / `roles` 自报——这是一个已实际复现的 P0 权限提升漏洞
（复现步骤见施工图 F1 任务卡）。规则写了没有贯彻，比没写更危险：它让审计
记录看起来有认证依据，实际依据只是调用方自己的说法。

**修复后的规则**：

1. **身份不再被丢弃**。共享的认证助手改为向下游返回
   `(UserIdentity | None, JSONResponse | None)` 二元组而不是只返回错误；
   所有受保护接口（Run 读取/取消/事件/观测数据、Gate 读取/审批、诊断导出、
   SSE、Actuator、DevTools）都能看到认证身份，即使部分接口（Actuator、
   DevTools 本身不作用于某个特定终端用户的资源）目前不需要用它做归属判断。

2. **资源归属校验**：存在认证身份时，读取或取消 Run、读取或审批 Gate，都
   要求该身份的 `organization` 与 Run 的 `user.organization` 一致；Gate
   通过其 `run_id` 找到归属 Run 后做同样比较。不一致返回 **404**
   （`RUN_NOT_FOUND` / `GATE_NOT_FOUND`），不是 403——403 会向一个无关的
   调用方确认"这个资源存在"，这本身就是它不该获得的信息。一个不存在的资源
   和一个存在但跨组织的资源，对外必须不可区分。跨组织隔离是企业部署的基本
   要求，不是可选的加固项。

3. **审批人身份由服务端生成，不信任请求体**：`decide` 端点在存在认证身份时，
   要求请求体的 `decided_by` 等于该身份的 `id`、`roles`（按集合比较）等于该
   身份的 `roles`；不一致时拒绝请求，返回 `IDENTITY_MISMATCH`（`409`），
   然后把 `decided_by` / `roles` 替换成身份自身的值再交给 Runtime——即便
   请求体已经"猜对"了这两个字段，落库的仍然是服务端持有的那份。这与
   `create_run` 对 `RunRequest.user` 的处理（第 11 节、`identity_matches`）
   完全对称：不一致就拒绝，不静默覆盖；静默覆盖会让调用方以为自己以声明的
   身份、以声明的角色行动了，而系统记录的是另一个身份。

4. **兼容路径保持不变**：当 `authenticate` 返回 `None`
   （`ApiKeyAuthnProvider` 可信服务模式）时，`decided_by` / `roles` 保留
   请求体原样的语义——这是第 11 节已经声明的信任边界，API Key 只认证了
   调用方服务，由它自己对声明的审批人身份和角色负责。这条路径的行为与 F1
   之前逐字节一致，依赖这个模式的既有部署不受影响。

**契约决策**：`HumanGateDecisionRequest.decided_by` / `roles` 保持必填、
类型不变，没有改成可选字段。曾评估"服务端已有身份时客户端可以省略这两个
字段"，但这会让 Gate 审批和 Run 创建（`RunRequest.user` 同样必填、同样要求
与认证身份一致）采用不对称的容错策略，也会触碰 §0.2 "不修改
`contracts/models.py` 已有字段类型和语义"的施工纪律。因此选择维持必填 +
精确匹配：客户端仍需显式声明它自认为的审批人和角色，服务端验证这份声明与
认证身份一致后才采信——这是纵深防御，也让"谁在批准、以什么权限批准"在请求
本身里就是显式可读的，不必反查身份提供方的 token 内容。

**这一节修复的是"规则写了没有贯彻"，不是新增规则**：第 11 节声明的身份权威
规则本身没有变化；变化的是它现在真的覆盖了除 `create_run` 之外的每一个受
保护接口。

## 13. 内置 OIDC/JWT AuthnProvider（F2，企业 IAM 对接）

**Gaia 不做身份系统。** 第 11 节已经说过 `AuthnProvider` 只是一个 SPI 接缝，
本任务（F2）在这个接缝上交付一个具体实现——`gaia.integrations.oidc.JwtAuthnProvider`
——但边界不变：企业已经运行着自己的 IdP（Keycloak、Okta、Entra ID、Ping 或
类似产品），认证终端用户、管理用户生命周期、授予角色都是 IdP 的职责。
`JwtAuthnProvider` 只做消费方的事——校验 IdP 签发的 JWT 的签名和标准
claim（`iss`/`aud`/`exp`/`nbf`），把 claim 映射成 `UserIdentity`——不铸造
令牌、不管理用户、不授予角色。没有做到的事不假装做到，口吻与第 1、10、11
节一致。

**三态语义原样适用**：验证失败（签名、`iss`、`aud`、过期、算法不在白名单、
claim 缺失或形状不对）一律抛 `AuthenticationError`，绝不返回 `None`——第 11
节已经论证过，`None` 是"可信服务、无终端用户身份"的专属语义，认证失败一旦
复用它就会被当成可信调用放行，是最坏的一类故障。`JwtAuthnProvider` 通过验证
的令牌总能映射出一个 `UserIdentity`（否则映射本身失败并抛异常），因此它从不
返回 `None`——那是 `ApiKeyAuthnProvider` 的语义，两者不混用。

**算法白名单只允许非对称签名算法**（`gaia.config.models.OIDC_ASYMMETRIC_ALGORITHMS`：
`RS*`/`PS*`/`ES*`），配置校验阶段拒绝 `none` 和任何对称算法（`HS*`）。这不是
随意的限制，而是防止两类已知攻击：`alg: none` 让令牌完全没有签名；
RS256/HS256"算法混淆"攻击则是利用验证逻辑如果同时认对称和非对称算法、又
按令牌自己声明的 `alg` 去选验证方式，攻击者就能把 IdP 公开发布的 JWKS 公钥
当 HMAC 密钥自己伪造签名——公钥本来就是公开的。`JwtAuthnProvider` 的防护是
**验证算法永远是构造时固定下来的白名单，从不由令牌头部的 `alg` 决定**：
`alg` 只用来快速拒绝和从 JWKS 里选公钥，真正喂给 `jwt.decode(algorithms=...)`
的永远是服务端自己的配置。

**Claim 映射必须可配置**：Keycloak 把角色放在嵌套的 `realm_access.roles`
里，Entra ID 用扁平的 `groups`，Okta 通常是自定义 claim——写死任何一种
布局都会让框架只能对接一家 IdP。`authn.claims.{subject,organization,roles}`
支持点号路径寻址嵌套 claim；映射到的 claim 缺失或形状不对（`roles` 必须是
非空字符串列表）一律抛 `AuthenticationError` 并点名具体 claim 路径——悄悄
拿不到 `roles` 意味着这个身份会以"无任何角色"通过认证，必须在认证阶段就
暴露，不能留到后面变成看起来像策略配置错误的故障。

**JWKS 缓存与失败退避**：签名验证公钥来自 IdP 发布的 JWKS，按可配置 TTL
缓存在内存里；拉取失败开启一个退避窗口，这段时间内复用已有缓存（即使已过
TTL）而不是让每次请求都触发一次可能压垮 IdP 的 HTTP 调用，从未成功拉取过
任何公钥时才以 `AuthenticationError` 拒绝。

**依赖是可选的**：`pyjwt`（`crypto` extra）声明在 `gaia-framework[oidc]`，
不进默认安装；`gaia.integrations.oidc` 模块本身不在顶层 `import jwt`，没装
这个 extra 时框架仍能正常 import，只有真正构造 `JwtAuthnProvider` 时才会
尝试导入并在失败时给出可操作的 `CONFIG_OPTIONAL_DEPENDENCY_MISSING:oidc`
错误，与 `RedisClientStarter` 处理 Redis 缺失依赖的方式一致。

完整配置项、三种 IdP 布局的 claim 映射示例，见
`developer-docs/http-api.md`「内置 OIDC/JWT AuthnProvider：企业 IAM 对接
（F2）」一节。本任务不实现 SAML，也不实现任何授权/权限模型——F2 只做认证，
授权仍然是 F1 落实的资源归属与角色校验规则（第 12 节）的范围。
