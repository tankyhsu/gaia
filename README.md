# Gaia

## 定位

Gaia 是一个面向企业 AI 应用的 Python 开发与运行框架。它通过 `GaiaApplication`、`gaia.yaml`、
Starter、自动配置和受控 Runtime，把 Model、Workflow、Context、Tool 与 Policy 装配为一个具备
工程边界的 AI 应用；Gaia Test Kit 从应用外部提供开发期测试。

Gaia 借鉴 Spring Boot 的声明式装配体验，但不复制 Spring Bean 容器，也不重新实现 Redis、
SQLAlchemy、模型、向量数据库或 Workflow 引擎。成熟库通过 Integration 接入；Gaia 只拥有
配置、资源作用域、运行围栏和稳定业务语义。

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
| Execution Runtime | Run、Policy、HumanGate、副作用、恢复和审计 |
| Runtime Safety Boundary | 服务端环境、工具白名单、角色、风险、写入模式和 Adapter 绑定 |
| Cache / RateLimiter | 可选 Redis 缓存与原子固定窗口限流 |
| Transactional Outbox | 业务事务内记录事件，事务外至少一次发布 |
| Actuator | 应用、组件、配置和健康状态的只读投影 |
| Gaia Dev Console | 业务构建者的初始化入口，以及开发者的组件、运行、配置、Prompt 和测试视图 |
| Gaia Test Kit | Dataset、执行器、Evaluator、Gate 与结构化测试报告 |
| Model Observability | 统一调用证据、Token/耗时/错误/重试、Run 关联与可选 OpenTelemetry |
| Cited RAG | 可替换 Loader/Parser/Chunker、幂等文档生命周期、权限过滤和 Citation |

## 快速开始

Gaia 文档按使用目标提供两套入口：

- [业务构建者指南](developer-docs/business-guide.md)：从能做什么、场景模板、真实样本和 Demo
  判断标准开始；
- [开发者指南](developer-docs/developer-guide.md)：从内部机制、项目生成、CLI、配置和 API 开始。

`gaia init` 支持文本与文档处理、企业知识回答、业务系统操作三类小型场景模板，并可按需激活
模型、Prompt Registry、RAG、Redis Cache 和 Outbox。新项目首次打开 Dev Console 的 Quick
Start 页面时可以选择相同场景；该写入入口只在开发态和初始化标记存在时开放。

框架仓库内快速查看内置 Starter：

```bash
uv sync --all-groups
uv run gaia starters
```

## 当前实现

Framework M4 已具备：

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

设计与验证证据见 [Gaia Framework 施工图](docs/施工图/README.md)和
[实现状态](docs/施工图/实现状态.md)。

Python 原生生命周期和 Core/Integration/Capability Pack 边界见
[Python 原生生命周期与集成边界](docs/施工图/11-Python原生生命周期与集成边界.md)。

Sandbox 的准确边界见
[Runtime 安全边界与 Sandbox](docs/施工图/09-Runtime安全边界与Sandbox.md)。当前 Sandbox 是
测试系统、凭据和 Adapter 的集成隔离，不是任意代码执行容器。

## 运行参考应用

Gaia 是 Python 应用框架，不通过 Docker 启动。框架仓库中的参考应用、Dev Console 和文档分别作为
本地开发进程运行：

```bash
uv sync --all-groups

# 终端 1：参考应用 API
make dev-api

# 终端 2：Dev Console
make dev-console

# 终端 3：开发者文档
make dev-docs
```

- API：`http://localhost:8000`
- Dev Console：`http://localhost:4173`
- Gaia 文档：`http://localhost:4175`

`controlled-task` 位于 `examples/controlled_task/`。它用于验证框架，不定义 Gaia 的公共能力边界。
Dev Console 不进入 Gaia Python 包，也不随业务应用启动。Prompt 菜单始终可见，但文件清单和
Registry 写路由还需要
`GAIA_DEVTOOLS_ENABLED=true` 才会注册；未开启时页面明确显示工作区状态。生产应用只安装所需
Starter，不部署 Gaia Dev Console，也不启用该开关。

## Gaia 文档

Gaia 文档提供两套入口：业务构建者从可实现的效果、场景模板和 Demo 验证开始；开发者从框架
机制、项目接入、CLI 和 API 开始。文档使用 MkDocs Material，Python API Reference 由
mkdocstrings 根据公开类型和 docstring 生成；HTTP API 继续使用 FastAPI 自动生成的 Swagger
UI、ReDoc 和 OpenAPI。

```bash
uv run mkdocs serve --dev-addr 127.0.0.1:4175
uv run mkdocs build --strict
```

文档首页只负责用户分流，两套路径共享必要页面但拥有不同的入口和阅读顺序。文档源不发布
`docs/施工图` 下的内部设计材料。

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

Redis 是可选基础设施，不保存 Run、Gate、Command、审计或长期记忆。启用两个独立 Starter：

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
