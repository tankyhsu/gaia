# 开发者指南

第一次给 Gaia 增加能力时，不要从 Runtime 开始。最短路径是：复制一个示例，替换业务工具，跑通一个只读场景，再增加受控写操作。

## 先建立四层模型

| 层 | 你写什么 | 常见文件 |
| --- | --- | --- |
| 场景 | 业务分几步、下一步是什么 | `flows.py` |
| 工具 | 怎样读取或修改真实业务系统 | `tools.py` |
| 控制 | 工具准入、风险、模型和 Runtime 配置 | `gaia.yaml` |
| 组装 | 把场景和工具注册进 Gaia | `app.py` |

身份、Run 生命周期、Gate、恢复和审计由 Gaia 提供。业务代码不要再实现一套平行机制。

## 第一个开发循环

### 1. 阅读最小示例

打开仓库中的 `examples/function_task/README.md`，然后按顺序看：

1. `flows.py`
2. `tools.py`
3. `gaia.yaml`
4. `app.py`

先找业务输入、输出和副作用，不要从框架类型开始读。

### 2. 启动本地 Temporal

```bash
uv run python scripts/temporal_dev_server.py \
  --host 127.0.0.1 \
  --port 7233 \
  --database var/gaia-function-task-temporal.db
```

`function_task` 使用 SQLite，不需要先运行 `make infra-up`。该命令只提供 PostgreSQL 和 Redis，
并不包含 Temporal。各启动方式的完整依赖和端口见[选择运行与部署方式](runtime-profiles.md)。

### 3. 启动 API 和 Worker

分别打开两个终端：

```bash
GAIA_API_KEY=gaia-dev-key \
uv run uvicorn examples.function_task.app:build --factory --reload
```

```bash
GAIA_API_KEY=gaia-dev-key \
uv run gaia worker \
  --config examples/function_task/gaia.yaml \
  --app examples.function_task.app:build
```

API 接收和查询 Run，Worker 执行 Temporal 分配的任务。生产环境中它们也应独立部署和扩容。

### 4. 先替换一个只读工具

选择一个没有副作用的真实查询，例如 `get_customer`：

- 适配器只做认证、参数转换和调用客户系统。
- 返回稳定、可序列化的业务结果。
- 不在适配器里偷偷执行第二个写操作。
- 为超时、未找到和上游故障定义明确错误。

先证明输入、执行、结果和证据能贯通，再增加写操作。

### 5. 再增加一个受控写操作

例如 `publish_report`：

- 在工具定义中声明副作用和风险。
- 在配置中限制允许的角色和场景。
- 让高风险动作在适配器执行前创建 Gate。
- 审批信息展示具体目标和影响。
- 给外部请求传递幂等键。
- 测试批准、拒绝、无权限和响应未知四条路径。

## 一次改动应该落在哪里

| 需求 | 优先修改 | 不要先修改 |
| --- | --- | --- |
| 增加业务步骤 | 场景定义 | Temporal Workflow 基础设施 |
| 接一个新系统 | 工具适配器和工具定义 | Gaia 审计数据库 |
| 改谁能执行 | 策略、角色和身份映射 | Prompt |
| 改哪些动作要审批 | 风险与 Gate 策略 | 工具执行后的补偿日志 |
| 改模型 | 模型 profile 和场景配置 | Runtime SPI |
| 增加客户可见证据 | 审计投影和 API/Console | 直接读取 Temporal 内部表 |

只有当现有扩展点无法表达一个已经验证的业务需求时，才考虑底层改动。

## 开发完成的最低标准

- 正常路径有自动化测试。
- 未授权用户和跨组织访问被阻止。
- 高风险适配器在批准前没有被调用。
- 重复请求不会重复产生副作用。
- Worker 中断后，结果不是静默丢失。
- 受控拒绝与系统失败能被区分。
- Run、Gate、工具和模型证据能被查询。
- 文档描述的是当前行为，不是规划中的能力。

仓库改动还必须遵循 `AGENTS.md` 和 `CONTRIBUTING.md` 的 change-set 流程。

## 什么时候再读底层文档

- 不理解 Run、Gate、Command：[核心概念](concepts.md)
- 调试等待、恢复、重试和预算：[运行机制](mechanisms.md)
- 规划服务和数据库：[Gaia 全景图](architecture.md)
- 做本地生产验收：[生产化本地验证](production-like.md)
- 集成外部客户端：[HTTP API](http-api.md) 与 [客户端集成](client-sdks.md)
