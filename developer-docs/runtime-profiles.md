# 选择运行与部署方式

Gaia 的“执行 Provider”和“启动方式”是两个不同维度。`in_process` 与 `temporal` 决定一次 Run
怎样执行；`make demo`、日常开发、`dev-full`、Production-like 和 Helm 决定整套服务怎样启动。
不要用端口号猜当前运行的是哪一档。

## 一张表选对入口

| 方式 | 用途 | Temporal | 入口与端口 | 是否是生产 |
| --- | --- | --- | --- | --- |
| `in_process` | 单元测试、自动化测试、单机 PoC | 不需要 | 由应用自己的 API 端口决定 | 否 |
| `make demo` | 第一次体验、确定性演示 | 脚本启动一次性本地 Server 和 Worker | Console `4180/#demo`；API `8010`；Docs 可选 `4175`；HR 可选 `4173` | 否 |
| 日常框架开发 | 修改示例、Runtime 或 Console | 开发者显式启动本地 Server 和 `make dev-worker` | API `8000`；Console `4173`；Docs `4175` | 否 |
| `make dev-full` | 本地验证完整基础设施和 HR 联调 | Compose 管理 | 单一 gateway `4181`：`/console/`、`/hr/`、`/docs/` | 否 |
| `make prod-up` | Compose 黑盒故障验收 | Compose 管理并使用 PostgreSQL | API gateway `8088`；Console `4180`；Temporal UI `8080`；Langfuse `3000` | 否 |
| Helm/Kubernetes | customer 生产部署 | 必须使用外部或平台管理的 Temporal | 由企业 Ingress、Gateway 或 Service 决定 | 是 |

## 执行 Provider 的边界

`runtime.execution.provider: in_process` 在 API 进程内完成一次 Run，并把终态和事件写入 Gaia
审计投影。它不支持跨进程 HumanGate 等待、Activity 重试、Worker 故障接管或分布式任务所有权；
产生副作用、Handoff 等需要继续执行的结果时会以 `DURABLE_EXECUTION_REQUIRED` 阻断。

`runtime.execution.provider: temporal` 需要可访问的 Temporal Server 和匹配 task queue 的 Gaia
Worker。customer 环境以及任何多副本、跨进程等待或关键写入场景都必须使用它。

## 第一次体验：`make demo`

```bash
uv sync --all-groups
make demo
```

这条命令始终启动隔离数据库、Temporal、Gaia API、Worker 和 Console，主入口是
`http://127.0.0.1:4180/#demo`。Docs 和仓库外的 HR Showcase 是增强体验：依赖完整时一并启动，
不可用时脚本会打印原因并继续保留核心演示。以终端最终打印的地址为准。

## 日常框架开发

`examples/controlled_task/gaia.yaml` 使用 Temporal。按下面顺序分别启动长期进程：

```bash
# 终端 1：本地 Temporal Server
uv run python scripts/temporal_dev_server.py \
  --host 127.0.0.1 \
  --port 7233 \
  --database var/gaia-dev-temporal.db
```

```bash
# 终端 2：应用 Worker
make dev-worker
```

```bash
# 终端 3：参考应用 API
make dev-api
```

```bash
# 终端 4：Dev Console
make dev-console
```

```bash
# 终端 5（可选）：开发者文档
make dev-docs
```

`make infra-up` 只提供 PostgreSQL 和 Redis，供选择这些 Integration 的开发 Profile 使用；它不
启动 Temporal，也不是 SQLite 示例的前置条件。

## 完整本地联调：`dev-full`

```bash
export DEEPSEEK_API_KEY='...'
make dev-full
```

这一档通过 Compose 启动 PostgreSQL、Redis、Temporal、Langfuse、Gaia、HR Showcase、Console
和开发 gateway。统一入口是 `http://127.0.0.1:4181/`。它使用 sandbox 环境和审批写入，属于
本地生产形态联调，不是生产部署模板。

## 验收与生产

`make prod-up` / `make prod-acceptance` 是本地 Compose 故障实验，验证多 API、Worker、Temporal
恢复、Gaia 审计投影和 Langfuse 关联，不能证明 Kubernetes 高可用或生产 SLA。

正式 customer 环境使用 Helm/Kubernetes。Gaia Chart 默认只部署 Gaia 拥有的 API、Worker、
迁移和 Temporal bootstrap 工作负载；PostgreSQL、Temporal、Langfuse、Ingress 与凭据生命周期
由企业平台负责。具体操作见仓库内 `infra/production-like/helm/README.md`。
