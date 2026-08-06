# HTTP 接口：认证、授权与边界

**完整的接口清单不在这里。** 它由 FastAPI 从路由、类型标注和 Pydantic 模型自动生成，
仓库里那份导出的契约是 `specs/openapi.json`，CI 会检查它与代码不漂移——手写一份
路径清单只会变成第二份事实，然后过期。

这一页讲的是**读 OpenAPI 看不出来的那部分**：谁在认证、身份从哪里来、哪些规则在
拒绝请求，以及为什么某个响应是 `404` 而不是 `403`。

本地地址取决于启动方式，不能把 `dev-full` 的 gateway 路径套到其他模式：

| 启动方式 | Swagger UI | OpenAPI JSON |
| --- | --- | --- |
| `make dev-api` | [127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) | [127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json) |
| `make demo` | [127.0.0.1:8010/docs](http://127.0.0.1:8010/docs) | [127.0.0.1:8010/openapi.json](http://127.0.0.1:8010/openapi.json) |
| `make dev-full` | [127.0.0.1:4181/api/docs](http://127.0.0.1:4181/api/docs) | [127.0.0.1:4181/api/openapi.json](http://127.0.0.1:4181/api/openapi.json) |
| `make prod-up` | [127.0.0.1:8088/docs](http://127.0.0.1:8088/docs) | [127.0.0.1:8088/openapi.json](http://127.0.0.1:8088/openapi.json) |

ReDoc 使用同一基址下的 `/redoc`；`dev-full` 经 gateway 时使用 `/api/redoc`。完整模式对照见
[选择运行与部署方式](runtime-profiles.md)。

主要接口分组：

| 分组 | 用途 |
| --- | --- |
| Runs | 创建、查询和取消 AI 任务 |
| Run Evidence | 按 Run 查询模型调用和无正文 Guardrail 决策 |
| Human Gates | 查询和处理人工确认 |
| Events | 获取 Run 的审计事件 |
| Evaluations | 开发期回放与质量验证 |
| Actuator | 应用、组件、配置、健康和运行摘要 |
| DevTools | 初始化和 Prompt 管理，仅开发环境开放 |

!!! warning "生产部署"
    DevTools 路由不应在生产环境启用。Swagger、ReDoc 和 OpenAPI 是否对外开放，也应由部署策略明确
    控制，不应把开发期接口说明暴露到公网。

OpenAPI 可以交给 OpenAPI Generator 等工具生成 Java、TypeScript 或 Python Client。生成的
Client 只负责协议调用，业务规则、Gaia Policy 和 Temporal 执行语义不复制到调用方。

## 认证：`AuthnProvider`

每个受保护的请求都要经过 `gaia.spi.auth.AuthnProvider.authenticate(headers)` 解析
调用方身份，结果只有三种，且**必须保持互不混淆**：

| 结果 | 含义 | HTTP 行为 |
| --- | --- | --- |
| 抛出 `AuthenticationError` | 认证失败：凭据缺失、格式错误或被拒绝 | 返回 `401 UNAUTHORIZED`，请求不进入 Runtime |
| 返回 `UserIdentity` | 认证成功，且携带一个终端用户身份 | 这个身份是**唯一事实源**，覆盖 `RunRequest.user` |
| 返回 `None` | 认证成功，但没有终端用户身份（可信服务调用） | `RunRequest.user` 按请求体原样生效 |

把"认证失败"和"认证成功但没有终端用户身份"这两种情况合并成同一个返回值
（比如两者都用 `None` 表示）是最坏的一类实现错误：这两种情况唯一的相同点是
都不抛异常，但正确的响应截然相反——前者必须拒绝请求，后者必须放行并信任
`RunRequest.user`。合并语义意味着某次认证失败会被当成"可信服务、按请求体的
身份执行"而放行。因此失败**必须**用异常表达，身份有无**必须**用返回值表达，
两个通道不能互相顶替。

**身份权威规则**：当 `authenticate` 返回一个 `UserIdentity` 时，它覆盖
`RunRequest.user`，不做字段合并。如果请求体里的 `user` 与这个身份不一致，
Gaia 拒绝请求（`IDENTITY_MISMATCH`），而不是静默用认证身份覆盖请求体——静默
覆盖会让调用方以为自己是以请求体里声明的身份执行的，实际上系统记录的是另一
个身份。`RunRequest.user` 是客户端提交的、不可信的输入：它的 `roles` 字段
直接参与 `gaia.runtime.safety.validate_roles` 和每个工具的 `required_roles`
校验，如果没有一个认证身份撑腰就把它当权威来源，等于允许调用方自己给自己
授予任意角色。

### 默认实现：`ApiKeyAuthnProvider`

`create_app` 不传 `authn` 参数时使用 `gaia.integrations.ApiKeyAuthnProvider`：校验
`X-Gaia-Api-Key` 头，Key 正确返回 `None`（可信服务、无终端用户身份），
Key 缺失或错误抛 `AuthenticationError`（`401 UNAUTHORIZED`）。这与引入
`AuthnProvider` 之前的行为逐字节一致。

!!! warning "信任边界"
    API Key 模式只认证了**调用方服务**，没有认证它代为执行的终端用户。使用
    `ApiKeyAuthnProvider` 时，Gaia 不会对 `RunRequest.user` 做任何交叉核验——
    框架假定调用方是一个可信的服务端进程，由它自己负责 `RunRequest.user`
    （包括其中声明的角色）的真实性。如果部署环境不能保证这一点（例如这个
    HTTP 接口对不完全可信、可能冒充任意用户的代码开放），必须提供一个直接
    认证终端用户并返回 `UserIdentity` 的 `AuthnProvider`，不能依赖
    `ApiKeyAuthnProvider`。这条边界的表述口吻与
    `src/gaia/runtime/safety.py` 对写入边界的实现一致：
    没有做到的事情不假装做到。

### 接入自定义身份源

```python
from gaia.api.app import create_app
from gaia.spi.auth import AuthnProvider

class MyAuthnProvider:
    async def authenticate(self, headers):
        ...  # 校验 Header/Token，认证失败抛 AuthenticationError，
             # 认证成功且能识别终端用户则返回 UserIdentity，
             # 认证成功但无终端用户身份则返回 None。

app = create_app(gaia_application=my_application, authn=MyAuthnProvider())
```

除 `ApiKeyAuthnProvider` 外，框架内置了一个 OIDC/JWT 实现
（`gaia.integrations.oidc.JwtAuthnProvider`，见下一节）；不内置 SSO 或 mTLS
集成，需要这些协议的应用自己实现 `AuthnProvider` 并接入。

### 内置 OIDC/JWT AuthnProvider：企业 IAM 对接

**边界先说清楚：Gaia 不做身份系统。** 企业已经运行着自己的 IdP
（Keycloak、Okta、Entra ID、Ping 或类似产品），由它负责认证终端用户、管理
用户生命周期、授予角色。`JwtAuthnProvider` 只做消费方的事：校验 IdP 签发的
JWT 的签名和标准 claim，把 claim 映射成 `UserIdentity`。**令牌签发、用户
生命周期、角色授予永远属于 IdP**，Gaia 不铸造、不存储、也不编辑它们——这条
边界的表述口吻与本文档第 1 节、`src/gaia/runtime/safety.py`
对 Sandbox 和 E3 认证边界的表述一致：没有做到的事不假装做到。

#### 配置

```yaml
authn:
  provider: oidc                # 默认 "disabled"：不设置这一节，行为和以前完全一致
  issuer: https://idp.example.com/realms/gaia
  audience: gaia-api
  jwks_url: ...                 # 可选；缺省时从 issuer 的 discovery 文档
                                 # （{issuer}/.well-known/openid-configuration）
                                 # 取 jwks_uri 派生，惰性完成，不在配置校验时联网
  leeway_seconds: 30            # 时钟偏差容忍窗口，作用于 exp/nbf/iat
  algorithms: [RS256]           # 必须是非对称签名算法，见下文
  jwks_cache_ttl_seconds: 300   # JWKS 缓存 TTL
  jwks_fetch_backoff_seconds: 30  # JWKS 拉取失败后的退避窗口
  claims:
    subject: sub
    organization: org_id
    roles: realm_access.roles   # 支持点号路径，寻址嵌套 claim
```

`create_app` 不传 `authn=` 参数时，若 `gaia.yaml` 里 `authn.provider: oidc`，
会自动用这份配置构造一个 `JwtAuthnProvider`；`create_app(authn=...)` 显式传参
始终优先于配置。`authn.provider` 缺省是 `"disabled"`，此时行为与引入这一节
配置之前逐字节一致——这是刻意的最小改动：`create_app` 早就从 `api_key` /
`GAIA_API_KEY` 这类基础配置项构造默认的 `ApiKeyAuthnProvider`，让它同样能从
`gaia.yaml` 的 `authn` 节构造 OIDC 实现只是同一条路径的自然延伸，没有引入
新的组件注册体系（`ComponentKind` 目前没有 AUTHN 这一类）——认证提供者是
`create_app` 直接消费的单例服务，不是 Runtime 装配期通过 `ComponentResolver`
解析给场景处理器用的依赖，为它单独铺一套 Starter/ComponentKind 机线超出了
F2 的范围。

#### Claim 映射：为什么必须可配置

各家 IdP 把角色放在完全不同的位置，写死任何一种都会让框架只能对接一家：

| IdP | 角色 claim 示例 | `claims.roles` 配置 |
| --- | --- | --- |
| Keycloak | 嵌套在 `realm_access.roles` | `realm_access.roles` |
| Entra ID | 扁平的 `groups` | `groups` |
| Okta | 常为自定义 claim（如 `myapp_roles`） | `myapp_roles` |

`claims.subject` / `claims.organization` / `claims.roles` 都支持点号路径
（`"a.b.c"` 表示逐层取 `claims["a"]["b"]["c"]`）。映射到的 claim 缺失，或
形状不对（`subject`/`organization` 要求非空字符串，`roles` 要求非空的字符串
列表），都会抛 `AuthenticationError` 并在错误信息里点名具体是哪个 claim
路径——一个身份悄悄拿不到 `roles` 意味着它会以"无任何角色"通过认证，这种
情况必须在认证阶段就暴露出来，而不是留到后面变成看起来像策略问题的故障。

#### 算法白名单：只允许非对称签名算法

`algorithms` 只接受非对称签名算法（`gaia.config.models.OIDC_ASYMMETRIC_ALGORITHMS`：
`RS256`/`RS384`/`RS512`、`PS256`/`PS384`/`PS512`、`ES256`/`ES256K`/`ES384`/`ES512`），
`none` 和任何对称算法（`HS*`）在配置校验阶段就会被拒绝。这不是随意的限制：

- **`alg: none` 绕过**：如果验证逻辑允许 `none`，攻击者可以发一个没有签名的
  "令牌"，声称自己是任何身份。
- **RS256/HS256 混淆攻击**：如果验证逻辑同时接受非对称和对称算法、又"贴心"
  地按令牌自己声明的 `alg` 去选验证方式，攻击者可以把 IdP 公开发布的 JWKS
  公钥当作 HMAC 密钥，自己签发一个 `alg: HS256` 的令牌——因为公钥本来就是
  公开的，这个"签名"任何人都能伪造。

`JwtAuthnProvider` 的防护是**令牌永远不能替自己选验证算法**：请求头的
`alg` 只用来（a）在做任何网络请求或密码学运算之前快速拒绝不在白名单里的
算法，和（b）从已经取到的 JWKS 里选一把候选公钥；真正的验证算法永远是
`JwtAuthnProvider` 构造时固定下来的 `algorithms` 列表本身，这个列表被原样
传给 `jwt.decode(..., algorithms=...)`，由 pyjwt 交叉核对令牌头部——不会有
任何代码路径把令牌头部的 `alg` 直接当成验证算法使用。

#### JWKS 缓存与拉取失败退避

签名验证用的公钥来自 IdP 发布的 JWKS，按 `jwks_cache_ttl_seconds` 缓存在
内存里，TTL 内的后续认证请求不会重新拉取。拉取失败（IdP 不可达、返回非
预期内容等）会开启一个 `jwks_fetch_backoff_seconds` 的退避窗口：这段时间内
不会再发起新的拉取请求，命中缓存里已有的公钥（哪怕已经过了 TTL——一次短暂
的 JWKS 故障不应该让几分钟前刚验证通过的密钥突然失效)；如果从未成功拉取过
任何公钥，则直接以 `AuthenticationError` 拒绝，而不是把每一次请求都变成一次
新的、可能压垮 IdP 的 HTTP 调用。

#### 依赖

`JwtAuthnProvider` 需要 `pyjwt`（带 `crypto` extra，RS/ES/PS 验签需要
`cryptography`），声明在 `gaia-framework[oidc]` 这个可选依赖组，不进默认
安装。`gaia.integrations.oidc` 模块本身不在顶层 `import jwt`，因此没有装
这个 extra 时框架仍然能正常 import；只有真正构造 `JwtAuthnProvider`（或
`authn.provider: oidc` 触发 `create_app` 去构造它）时才会尝试 `import jwt`，
没装依赖会抛出 `RuntimeError("CONFIG_OPTIONAL_DEPENDENCY_MISSING:oidc")`，
与 `RedisClientStarter` 处理 Redis 可选依赖缺失的方式一致。

### 资源归属：跨组织隔离

存在认证身份（`authenticate` 返回 `UserIdentity`）时，以下接口会额外校验该
身份的 `organization` 与目标资源所属 Run 的 `user.organization` 是否一致：

- `GET /v1/runs/{run_id}`、`.../events`、`.../events/stream`、
  `.../model-invocations`、`.../guardrail-decisions`、`.../tool-invocations`；
- `POST /v1/runs/{run_id}/cancel`；
- `GET /v1/diagnostics/runs/{run_id}/bundle`；
- `GET /v1/human-gates/{gate_id}`、`POST /v1/human-gates/{gate_id}/decision`
  （通过 Gate 的 `run_id` 找到归属 Run 再做同样比较）。

不一致时返回 **`404`**（`RUN_NOT_FOUND` / `GATE_NOT_FOUND`），**不是** `403`：
403 会向一个与该资源无关的调用方确认"这个 Run/Gate 确实存在"，这本身就是
调用方不应获得的信息。一个不存在的资源和一个存在但不属于自己组织的资源，
对外表现必须相同。

当 `authenticate` 返回 `None`（可信服务模式，见上文的信任边界说明）时不做
归属校验——这与该模式"不认证终端用户、由调用方自己负责"的既有语义一致，
不是遗漏。

### 列出 Run：`GET /v1/runs`

```http
GET /v1/runs?status=waiting_human&scenario_id=refund.request&limit=50&cursor=...
```

按创建时间倒序返回一页 Run。查询参数：

| 参数 | 说明 |
| --- | --- |
| `status` | 按 `RunStatus` 精确匹配过滤，可选 |
| `scenario_id` | 按 scenario id 精确匹配过滤，可选 |
| `limit` | 单页条数，默认 50，最大 200；超过 200 返回 `422`（**拒绝，不做静默截断**），与 `actuator.py` 的 `window_hours` / `stale_after_seconds` 等既有边界参数的处理方式一致 |
| `cursor` | 上一页响应 `next_cursor` 的原样传回；**不透明 token**，不要解析或自行构造 |

响应是 `RunPage`：`items`（`RunSnapshot` 数组）+ `next_cursor`（`null` 表示已到最后一页）。
排序键是 `(created_at DESC, run_id DESC)`——`run_id` 只用于给同一时间戳内的多个 Run 打破
平局，不代表任何业务含义。分页用的是游标，不是 `offset`：`offset` 分页在翻页过程中如果有
新 Run 插入队首，会导致后续页整体错位、漏掉或重复某些行；对一个审计场景来说"漏掉某条 Run"
是不可接受的，游标（"取严格早于上次看到的最后一条"）不会有这个问题——代价是不能跳页，只能
顺序翻页，这个取舍是刻意的。

**跟「资源归属：跨组织隔离」完全相同的组织隔离规则、完全相同的可信服务例外**：

- 存在认证身份时，返回的 Run **只**限定在该身份的 `organization` 内——过滤发生在 SQL
  查询里（审计投影上的 `organization` 索引列），不是先取回一批再在 Python 里筛掉不属于
  自己的行。这个区别不是吹毛求疵：一旦"先取回再筛"的写法被后续改动误用（例如给某个内部工具
  复用同一段查询逻辑却忘了带上过滤），就会变成一次性把全量数据吐出去的漏洞；放进 SQL
  WHERE 子句里没有这个风险。列表接口是最容易一次性泄露全量数据的地方，这条不是附加要求。
- `authenticate` 返回 `None`（可信服务模式）时，**不做任何组织过滤**，返回值跨越所有
  组织——这不是遗漏，是与 `authorized_run` 完全一致的既有信任边界：可信服务
  调用没有可供比较的终端用户身份，Gaia 不假装能替它做归属判断，由调用方自己负责按需
  过滤或只在可信的内部场景使用这个模式。需要端到端的组织隔离时，部署必须提供会返回
  `UserIdentity` 的 `AuthnProvider`。

### 列出一个 Run 开过的所有审批：`GET /v1/runs/{run_id}/human-gates`

```http
GET /v1/runs/gaia-run-2ad04ec8.../human-gates
```

按创建时间正序返回这个 Run 开过的**每一个** Gate，不只是当前挂起的那个。Run 完成之后
`pending_gate_id` 会被清空，所以这是事后回答"谁批准了这次写入"的唯一途径。

组织隔离与单 Run 读取完全一致：属于其他组织的 Run 返回 `404`，不是 `403`——`403` 会向不该
知情的人确认这个 Run 存在。

### Human Gate 审批：身份由服务端生成，不信任请求体

`POST /v1/human-gates/{gate_id}/decision` 的请求体仍然要求 `decided_by`
和 `roles`（契约未变，二者依旧是必填字段），但当存在认证身份时，这两个
字段**不再是权威来源**：

- 服务端要求请求体的 `decided_by` 等于认证身份的 `id`、`roles`（按集合比较，
  与顺序无关）等于认证身份的 `roles`；
- 不一致时拒绝请求，返回 `409 IDENTITY_MISMATCH`——**不静默改写**成认证身份
  的值。静默改写会让调用方以为自己是以请求体里声明的身份、以声明的角色批准的，
  而实际落库的是另一个身份，这正是 E3 定下的"身份不一致就拒绝"规则在 Gate
  审批上的落实；
- 一致时，落库的 `decided_by` / `roles` 取自认证身份自身（而不是原样透传请求
  体），因此审批记录的权威来源永远是 `AuthnProvider` 解析出的身份，请求体
  只是调用方对同一件事的显式重复声明，用于早期发现调用方自己的假设错误。

`decided_by` / `roles` 为什么仍是必填而不是改成可选：让服务端有身份时直接
用身份的值、客户端可以省略，会让 Gate 审批和 `create_run` 对 `RunRequest.user`
的处理方式变得不对称（后者同样必填、同样要求与认证身份一致），也会触碰
"不修改 `contracts/models.py` 已有字段类型和语义"的施工纪律。必填 + 精确匹配
是刻意的纵深防御：谁在批准、以什么角色批准，在请求本身里就是显式可读的，
不必去反查 token 内容。

当 `authenticate` 返回 `None`（可信服务模式）时，`decided_by` / `roles`
保留请求体原样的语义，行为与 F1 之前逐字节一致——这与 API Key 模式对
`RunRequest.user` 的信任边界完全对称：调用方自己对它提交的审批人身份和
角色的真实性负责。

Guardrail 决策查询：

```http
GET /v1/runs/{run_id}/guardrail-decisions
```

响应包含阶段、规则 ID/版本、动作、风险分、原因码和耗时。`input_ref` / `output_ref` 是内容
哈希引用，不是业务正文。

### Runtime Provider 与 API 语义

`POST /v1/runs` 的接口契约不会因 Runtime Provider 改变，但 Provider 的适用边界是强约束：

- customer 环境必须配置 `runtime.execution.provider: temporal`；实际部署拓扑由 Helm/Kubernetes
  的 Deployment、HPA 和调度配置决定，不在 Gaia 应用配置里重复声明。
- `in_process` 只用于开发、自动化测试和单机 PoC。它在 API 进程内执行一次 Scenario，并把终态 Run
  与事件写入 Gaia 审计投影，不提供跨进程任务所有权、HumanGate 等待、Activity 重试或故障接管。
- in-process 执行若产生 SideEffect、Handoff 或其他需要跨请求继续的结果，Run 会以
  `DURABLE_EXECUTION_REQUIRED` 阻断；Gaia 不执行副作用，也不会静默降级为较弱的生产语义。

LangGraph Checkpointer 保存图状态，Gaia 审计投影保存长期业务证据，Temporal 负责生产环境的
分布式执行与恢复。这三者职责不同，前两者不能替代生产 Runtime。

开发期 Prompt 工作区状态：

```http
GET /devtools/prompts
```

仅在 `GAIA_DEVTOOLS_ENABLED=true` 时注册。响应明确区分 `disabled`、`file` 和 `postgres`；
文件模式只返回 Artifact 标识、版本、相对路径和内容哈希，不返回 Prompt 正文。
