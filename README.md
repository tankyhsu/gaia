# Gaia

[在线开发者文档](https://tankyhsu.github.io/gaia/)由 MkDocs 构建；`main` 分支通过完整文档校验后，
GitHub Actions 自动发布到 Pages。仓库中的 Markdown 仍可直接在 GitHub 阅读。

## 一条命令看效果

克隆仓库后，先看看它能做什么，不必先读文档：

```bash
uv sync --all-groups
make demo
```

`make demo` 会启动一个一次性的 Temporal 开发服务器和应用 Worker，建立干净、独立的
Gaia 数据库并迁移它，预置几条有代表性的运行——一次经
人工审批通过并完成的受控写入、一次被人工拒绝、一次在触达人工之前就被跨组织策略拒绝——
然后启动参考 API 和 Dev Console。核心演示入口始终是：

```
Open http://127.0.0.1:4180/#demo to see what Gaia is and what each seeded run proves.
```

打开它，点任意一条运行，证据页签会说明这次运行依据哪版策略、谁批准的、拒绝了什么。开发者
文档和仓库外的 HR Showcase 依赖完整时会一并启动；缺失时脚本会说明原因并继续核心演示，实际
地址以终端最终输出为准。
`make demo` 用独立端口（Temporal 7233、API 8010、Console 4180）和独立数据库
（`var/gaia-demo*.db`，绝不触碰 `var/gaia.db`），不会影响已经在跑的
`make dev-api` / `make dev-console`；`Ctrl+C` 退出即可清理本次启动的进程，不留后台残留。
失败时会打印下一步该做什么，而不是一段裸 traceback。各运行方式的依赖和端口见
[选择运行与部署方式](developer-docs/runtime-profiles.md)。

## 本地验证生产拓扑

要验证多 API/Worker、Temporal PostgreSQL 恢复和 Langfuse 自托管链路：

```bash
make prod-up
make prod-acceptance
make prod-down
```

完整拓扑、故障实验和边界见
[本地 Production-like 验证](developer-docs/production-like.md)。

## 定位

Gaia 是面向企业 Agent 的 Python **应用容器、受控边界和交付脚手架**。它的生产定位是
Helm/Kubernetes 上的分布式受控执行，不把简单单机应用作为目标市场；in-process Runtime 只用于
降低开发、测试和 PoC 的启动成本：

- **逻辑编排由 LangGraph 负责**：应用定义 State、节点与条件路由，Gaia 只提供窄
  `ScenarioRunner` 适配边界。
- **开发执行由 Gaia in-process Runtime 负责**：仅适用于开发、测试和单机 PoC；Run 与事件证据
  写入 Gaia 数据库，应用可以继续使用 LangGraph Checkpointer 保存图状态。
- **分布式耐久执行由 Temporal.io 负责**：任何多副本部署，以及跨进程等待、HumanGate、
  关键写入、自动重试和故障接管，都必须显式选择 Temporal。
- **可观测性由 Langfuse 负责**：通过 OpenTelemetry 关联 Workflow、模型、Token、成本和
  Prompt 版本。
- **Gaia 负责应用装配与治理**：`gaia.yaml`、Starter、认证授权、策略检查、应用 Worker
  入口、只读 Actuator 和 Test Kit。

Gaia 要回答的问题不是“怎样再造一套 Workflow 引擎”，而是这些成熟产品组合之后：配置里
声明的策略是否就是实际执行的策略、外部写入是否经过统一检查点、出问题时能否证明当时依据
哪个版本以及谁批准了它。

以下控制面能力已经实现：

- **不可绕过的写入边界**：Scenario、LangGraph 或模型产生的副作用提案，在注册 Temporal
  Command Activity 前必须经过角色、风险等级、环境写入上限、工具白名单和 Adapter 定义
  一致性检查。
- **执行 Provider 只有一份真相**：in-process 模式在请求进程内完成一次运行并把证据写入 Gaia；
  Temporal 模式由 Workflow 持有状态迁移、HumanGate Update、Activity Retry、预算和恢复。
  customer 生产环境必须选择 Temporal；实际副本数和调度策略由 Helm/Kubernetes 负责。
- **显式副作用策略**：`reconcilable`、`idempotent` 和
  `at_most_once_manual` 仍是 Gaia 的业务安全契约，但其执行与重试由 Temporal Activity
  承担。
- **可验证的版本证据**：顶层公共 API `gaia.fingerprint` 把 `rules_version`
  这类版本号锚定在真实内容上而不是手填字符串；策略收紧覆盖只能让策略更严格，一旦生效就
  会改变记录下来的策略版本，审计时可以核对当时生效的究竟是哪份策略。
- **认证身份是唯一事实来源，且按组织隔离**：受保护接口都以服务端认证身份为准，不信任
  请求体自称的身份或角色；跨组织的资源与不存在的资源对外必须表现一致。内置
  `JwtAuthnProvider` 对接企业已有的 OIDC/JWT IdP（Keycloak、Okta、Entra ID 等）。
- **统一证据读取**：API、Actuator、诊断包和 Console 都读取 Gaia 审计投影；Temporal 模式
  同时保留可回放的 Workflow History，in-process 模式则只承诺单进程内完成的运行与事件证据。

声明式装配服务于“配置里能看到的东西，等于实际在跑的东西”：API 和 `gaia worker` 进入
同一个应用 composition/lifespan，Actuator 展示的组件图与真实依赖同源。成熟的模型 SDK、
Temporal、LangGraph、Langfuse、SQLAlchemy、Redis 和向量数据库都通过 Integration 接入，
Gaia 不重新实现它们。

**Gaia 不保证、也不试图替代什么**：

- 不构成任何合规认证；上述机制是工程实现，不是通过审计或认证的声明。
- 不替代企业已有的 IdP 或审计系统：用户认证、身份生命周期管理和角色授予仍是 IdP 的职责，
  `JwtAuthnProvider` 只校验 IdP 签发令牌的签名与标准声明，记录审批发生时的身份与角色证据。
- 当前的跨组织隔离只到"组织"这一级；同组织内部更细粒度的授权由业务应用自己实现。
- in-process 模式不是生产部署选项，也不提供分布式任务所有权、跨进程 HumanGate 等待、Worker 故障接管或 Activity
  Retry；需要这些语义时必须使用 Temporal，并承担 namespace、task queue、容量和灾备运维。
- 不承诺 LangGraph 节点本身具备副作用重放安全性；客户 Adapter 仍需按声明的恢复策略实现。
- `gaia check` 的 AST 导入期纯净性检查是一个 best-effort 的静态 lint，不是隔离或安全边界，
  绕过方式很多（动态 import、间接调用、第三方库内部 I/O）。

## 设计决策与自查缺陷

如果只读一份文档，读[工程纪实：决策、缺陷与被否决的方案](docs/工程纪实-决策与缺陷.md)
（约 20 分钟）。它记录的是这次重构里做过的判断、**自己找出的三个"声称已强制、实际没有
强制"的缺陷**，以及主动否决的方案和理由——包括一个看起来生效、连审计证据都为它背书，
实际却拦不住任何调用的治理开关。

## 攻防演示

以上每一条“不可绕过”都可以被现场攻击一次。`make attack-demo`（脚本见
`scripts/attack_demo.py`）在无 Docker、无网络、无 PostgreSQL 的前提下依次执行七类曾经
真实复现过的攻击——伪造 approver 角色、跨组织读取/审批、`alg=none` 令牌、
RS256/HS256 密钥混淆、从配置放宽策略、绕过 `deny_tools` 直接调用工具、导入期解析密钥——
并对每一条打印攻击内容、实际结果，以及
"哪一行代码在强制执行这条防线"。任意一条防线未能生效，脚本以非零状态退出，因此它同时是一
个回归检查，而不是一次性演示。Temporal Server/Worker 的断电恢复和跨副本调度由独立的真实
Temporal 验收覆盖，不由这个 Gaia-only 攻防脚本模拟。

## 核心概念

| Gaia | 作用 |
| --- | --- |
| `GaiaApplication` | 零副作用装配计划与 Python 原生资源作用域 |
| `gaia.yaml` | 应用、Profile、Starter 和组件配置 |
| Starter | 提供默认配置、装配条件和 ComponentSpec |
| Auto Configuration | 根据配置和依赖建立可解释组件图 |
| ApplicationContext | 运行中组件与配置的不可变快照 |
| Integration | 把成熟第三方 Client 绑定到配置、scope 和健康检查 |
| Capability Pack | 组合端口与 Integration 的可选行为，例如 Outbox |
| Temporal Execution | Workflow、Activity、HumanGate、重试、恢复和执行历史 |
| Runtime Safety Boundary | 服务端环境、工具白名单、角色、风险、写入模式和 Adapter 绑定 |
| Cache / RateLimiter | 可选 Redis 缓存与原子固定窗口限流 |
| Transactional Outbox | 业务事务内记录事件，事务外至少一次发布 |
| Actuator | 应用、组件、配置、健康状态和 Temporal 运行状态的只读投影 |
| Gaia Dev Console | 开发者的项目初始化、组件、运行、配置、Prompt 和测试视图 |
| Gaia Test Kit | Dataset、执行器、Evaluator、Gate 与结构化测试报告 |
| Model Observability | 统一调用证据、Token/耗时/错误/重试、Run 关联与可选 OpenTelemetry |
| Cited RAG | 可替换 Loader/Parser/Chunker、幂等文档生命周期、权限过滤和 Citation |

## 快速开始

Gaia 文档面向应用开发者和交付工程师：

- [三个 Case](developer-docs/try-it.md)：把真实场景映射到 Gaia 的场景、策略、Gate、工具和证据；
- [开发者指南](developer-docs/developer-guide.md)：从框架机制、项目生成、CLI、配置和 API 开始。

`gaia init` 支持文本与文档处理、企业知识回答、业务系统操作三类小型场景模板，并可按需激活
模型、Prompt Registry、RAG、Redis Cache 和 Outbox。新项目首次打开 Dev Console 的 Quick
Start 页面时可以选择相同场景；该写入入口只在开发态和初始化标记存在时开放。

框架仓库内快速查看内置 Starter：

```bash
uv sync --all-groups
uv run gaia starters
```

## 当前实现

当前版本已具备：

- 配置、Profile、SecretRef 和来源追踪；
- Starter、条件装配、组件覆盖和 `ApplicationContext`；
- `GaiaApplication.lifespan()`、`AsyncExitStack` 与失败回滚；
- 与业务无关的 Runtime 依赖契约；
- Actuator 对应用、组件、生效配置和运行状态的只读投影；
- 可读错误目录、Trace ID、操作建议和可重试语义；
- `gaia init/check/doctor/add-workflow/dev/starters/migrate` CLI；
- 24 小时 Run、耗时、HumanGate、错误、Outbox 和数据库争用的运行摘要；
- SQLite 默认档，以及 PostgreSQL 事务库、LangGraph checkpoint、长期记忆和 pgvector 扩展档；
- 共享 redis-py Client 的可选 CacheProvider、RateLimiter Integration；
- PostgreSQL Transactional Outbox、租约领取、重试、死信与进程内 Publisher；
- 可插拔 Gaia Test Kit；支持版本化数据集、确定性断言和通用通过率 Gate，应用可提供自己的指标和质量模型；
- 服务端 `mock/sandbox/customer` 环境与不可绕过的写入安全边界；
- 独立于生产 Runtime 的 Gaia Dev Console，提供业务场景初始化，以及开发概览、组件、运行、
  只读生效配置、Provider 感知的 Prompt Workspace 和测试视图；
- 独立的 `controlled_task` 参考应用。
- 不记录正文的模型调用证据、按 Run 查询、开发期摘要和可选 OpenTelemetry 导出。
- 显式 `rag-postgres` Starter 提供从文档摄取到带来源引用检索结果的最小闭环。
- 应用由 `gaia.yaml`（`scenarios.modules`）与被 `@scenario`/`@read_tool`/`@write_tool`
  装饰的普通函数声明式装配：`scenario-runtime` Starter 在启动期发现这些函数并把
  `RuntimeAssembler` 注册为组件，`create_app(gaia_application=...)` 直接从组件图取用，
  不需要手写 `GaiaAppBuilder` composition；`gaia init` 生成的项目和
  `examples/function_task` 都是这条路径。

设计与验证证据见 [Gaia Framework 施工图](docs/施工图/README.md)和
[Gaia 架构全景图](developer-docs/architecture.md)。历史迁移过程见
[Temporal 迁移任务清单](docs/施工图/17-TemporalIO-迁移任务清单.md)。

Python 原生生命周期和 Core/Integration/Capability Pack 边界见
[Python 原生生命周期与集成边界](docs/施工图/11-Python原生生命周期与集成边界.md)。

当前 Sandbox 边界见[Gaia 架构全景图](developer-docs/architecture.md)和
[运行机制](developer-docs/mechanisms.md)：它是测试系统、凭据和 Adapter 的集成隔离，不是任意
代码执行容器。早期设计过程记录在
[Runtime 安全边界与 Sandbox](docs/施工图/09-Runtime安全边界与Sandbox.md)，其中旧包路径等
名称只代表当时的实现，不作为当前 API 参考。

部署拓扑见[选择运行与部署方式](developer-docs/runtime-profiles.md)和
[Gaia 架构全景图](developer-docs/architecture.md)：生产执行由 Temporal Server 和独立 Gaia
Worker 组成；API 可以水平扩展，Workflow ID、task queue、History replay 和 Activity Retry
提供跨副本执行协调。PostgreSQL 只承载应用数据，Outbox dispatcher 使用自己的事件行级租约
机制，与 Temporal Workflow 调度无关。

## 运行参考应用

只是想看看效果，用开头的 `make demo` 即可——它自带干净的数据库和几条预置运行。修改参考
应用或框架本身时，`controlled_task` 使用 Temporal，需要分别启动以下长期进程：

先安装依赖：

```bash
uv sync --all-groups
```

终端 1 启动本地 Temporal Server：

```bash
uv run python scripts/temporal_dev_server.py \
  --host 127.0.0.1 \
  --port 7233 \
  --database var/gaia-dev-temporal.db
```

终端 2 启动应用 Worker：

```bash
make dev-worker
```

终端 3 启动参考应用 API：

```bash
make dev-api
```

终端 4 启动 Dev Console：

```bash
make dev-console
```

终端 5 可选启动开发者文档：

```bash
make dev-docs
```

- API：`http://127.0.0.1:8000`
- Dev Console：`http://127.0.0.1:4173`
- Gaia 文档：`http://127.0.0.1:4175`

这里不需要 `make infra-up`：默认示例使用 SQLite。该命令只启动 PostgreSQL 和 Redis，也不会
替你启动 Temporal。完整模式对照见[选择运行与部署方式](developer-docs/runtime-profiles.md)。

`controlled-task` 位于 `examples/controlled_task/`。它用于验证框架，不定义 Gaia 的公共能力边界。
Dev Console 不进入 Gaia Python 包，也不随业务应用启动。Prompt 菜单始终可见，但文件清单和
Registry 写路由还需要
`GAIA_DEVTOOLS_ENABLED=true` 才会注册；未开启时页面明确显示工作区状态。生产应用只安装所需
Starter，不部署 Gaia Dev Console，也不启用该开关。

## Gaia 文档

Gaia 文档面向应用开发者、平台工程师和交付工程师，从具体 Case 进入框架
机制、项目接入、CLI 和 API。文档使用 MkDocs Material，Python API Reference 由
mkdocstrings 根据公开类型和 docstring 生成；HTTP API 继续使用 FastAPI 自动生成的 Swagger
UI、ReDoc 和 OpenAPI。

```bash
uv run mkdocs serve --dev-addr 127.0.0.1:4175
uv run mkdocs build --strict
```

文档首页说明能力与边界，参考 Case 用于解释框架行为。文档源不发布 `docs/施工图`
下的内部设计材料。

## 框架研发

Gaia 自身使用 Codex 原生 Hook 驱动的 Change Set 工作流。实现、测试、文档、生成契约和发布
影响必须作为同一次变更完成；GitHub Actions 在干净环境重新运行确定性测试、PostgreSQL/Redis
集成、前端 E2E、文档和发布包 Smoke。贡献方式见 [CONTRIBUTING.md](CONTRIBUTING.md)，内部
机制见 [Agent 研发 SOP 与流水线](docs/施工图/12-Agent研发SOP与流水线.md)。这些研发规约不进入
Dev Console 或面向 Gaia 使用者的文档导航。

## PostgreSQL 档

PostgreSQL 是可选扩展，SQLite 仍是零依赖默认档。PostgreSQL profile 将同一实例分别用于 Gaia
事务表、LangGraph checkpoint、长期记忆和 pgvector 语义索引，四类能力拥有独立配置和生命周期。

```bash
uv sync --all-groups --extra postgres
docker compose -f infra/dev/compose.yaml up -d postgres
export GAIA_POSTGRES_URL='postgresql://gaia:gaia-dev-password@127.0.0.1:54329/gaia'
```

该 Compose 只提供本地开发依赖，不启动 Gaia 应用、Dev Console 或文档。

参考 PostgreSQL profile 使用 OpenAI-compatible embedding 接口，默认验证配置为硅基流动
`Qwen/Qwen3-Embedding-0.6B` 的 64 维输出。启动前提供：

```bash
export SILICONFLOW_API_KEY='...'
```

该配置只是 reference profile，业务应用可以替换成其他兼容服务或本地 embedding 服务。

应用启动前会执行框架自带的 Alembic 迁移。独立执行迁移：

```bash
GAIA__PROFILE=postgres \
GAIA_POSTGRES_URL='postgresql://gaia:password@localhost:5432/gaia' \
uv run gaia migrate --config examples/controlled_task/gaia.yaml
```

数据库连接串和 embedding API Key 均使用 `SecretRef`，Actuator 只保留引用，
不保存解析后的凭据。

## Redis 缓存与限流

Redis 是可选基础设施，不保存 Temporal Workflow、HumanGate、Command、审计或长期记忆。
启用两个独立 Starter：

```bash
uv sync --all-groups --extra redis
uv run gaia init /tmp/redis-app \
  --starter cache-redis \
  --starter rate-limit-redis
docker compose -f infra/dev/compose.yaml up -d redis
export GAIA_REDIS_URL='redis://127.0.0.1:63799/0'
```

```yaml
starters:
  - cache-redis
  - rate-limit-redis
redis:
  url:
    env: GAIA_REDIS_URL
cache:
  provider: redis
  default_ttl_seconds: 300
rate_limit:
  provider: redis
```

`CacheProvider` 只接受带 TTL 的字节值；`RateLimiter` 当前提供 Lua 原子固定窗口实现。二者共享
一个 application-scoped redis-py Client。调用方决定限流维度和额度，Redis 不可用时抛出错误，
Integration 不静默放行。

## Transactional Outbox

`outbox-postgres` 会同时选择 PostgreSQL operational store 和 `publisher-in-process`。应用在自己的
数据库事务中调用 `SqlAlchemyOutboxStore.enqueue(session, event)`，提交后由
`OutboxDispatcher.dispatch_once()` 领取并发布。投递语义是至少一次，订阅处理器必须幂等。

当前没有 Kafka、RabbitMQ 或 Redis Streams Publisher。MQ 选型触发条件和边界见
[Redis、限流与 Outbox](docs/施工图/10-Redis限流与Outbox.md)。

## 非目标

- 通用 Agent 聊天产品；
- 拖拽式低代码 Workflow；
- 模型训练和推理平台；
- 向量数据库控制台；
- 客户业务页面；
- 客户发现、咨询和项目管理工具；
- 用静态前端数据伪装尚未存在的框架能力。
