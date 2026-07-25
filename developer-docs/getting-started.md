# 创建第一个项目

## 准备环境

当前 Gaia 尚未发布到公共包仓库，需要 Python 3.12 和
[uv](https://docs.astral.sh/uv/)。

```bash
export GAIA_REPO=/absolute/path/to/gaia
export APP_DIR=/absolute/path/to/my-gaia-app

cd "$GAIA_REPO"
uv sync --all-groups
uv run gaia init "$APP_DIR" --name my-gaia-app
```

`gaia init` 默认生成最小项目。也可以直接选择场景和组件：

```bash
uv run gaia init "$APP_DIR" \
  --template knowledge \
  --component prompt-registry
```

| 模板 | 适合的应用 |
| --- | --- |
| `basic` | 总结、分类、信息抽取和内容生成 |
| `knowledge` | 基于企业资料回答并标明来源 |
| `approval` | 调用业务接口并在关键步骤人工确认 |

## 安装并检查

```bash
cd "$APP_DIR"
uv add --editable "$GAIA_REPO"
uv sync
uv run gaia check --config gaia.yaml
uv run pytest -q
```

正式交付时，把 editable 依赖替换为固定版本的内部 wheel。

## 启动开发服务

```bash
GAIA_API_KEY=local-dev-key \
GAIA_DEVTOOLS_ENABLED=true \
GAIA_PROJECT_ROOT=. \
uv run gaia dev --app my_gaia_app.app:app --reload
```

验证服务：

```bash
curl -fsS http://127.0.0.1:8000/health/live
```

创建第一个 Run：

```bash
curl -fsS -X POST http://127.0.0.1:8000/v1/runs \
  -H 'Content-Type: application/json' \
  -H 'X-Gaia-Api-Key: local-dev-key' \
  -H 'Idempotency-Key: quick-start-001' \
  -d '{
    "scenario_id": "hello",
    "mode": "mock",
    "user": {
      "id": "developer",
      "organization": "example",
      "roles": ["user"]
    },
    "request": {"text": "Gaia"}
  }'
```

## 查看运行证据

打开 Dev Console 的“运行”，输入 Run ID 后可以在同一个详情区切换：

- **运行结果**：最终状态与业务结果；
- **模型调用**：模型、Prompt 版本、Token 和耗时；
- **安全决策**：输入、检索、输出和工具边界的放行、改写、阻断或异常；
- **事件链**：Runtime 状态变化和执行顺序。

新项目不会自动获得客户行业规则。先使用确定性 Pattern 验证接入，再根据真实数据选择
Presidio、Guardrails AI 或项目自有 Guardrail。装配方式见[安全防护](guardrails.md)。

Prompt 菜单不会因 Provider 未启用而消失。默认文件模式展示只读 Artifact 清单；需要频繁调整、
多人发布和回滚时再切换到 PostgreSQL Registry。开发工作区必须显式开启，生产应用不会注册
这些管理路由。

## 生成项目里有什么

| 文件 | 用途 |
| --- | --- |
| `src/<package>/app.py` | ASGI 入口和 Scenario 注册 |
| `src/<package>/scenarios/` | 应用拥有的场景代码 |
| `prompts/` | Git 管理的 Prompt Artifact |
| `gaia.yaml` | Profile、Starter 和基础设施配置 |
| `tests/` | 穿过真实 Runtime 的应用测试 |
| `.env.example` | 所需环境变量，不包含真实密钥 |

生成的 `app.py` 同时提供 `create_application()` 和模块级 `app`。Uvicorn 使用 `app`；测试调用
`create_application()`，确保每个 Case 获得独立的 `GaiaApplication` 生命周期。

Prompt 和 RAG 的相对目录以 `gaia.yaml` 所在目录为基准，不依赖启动命令的当前工作目录。

继续阅读：[命令行参考](cli.md)。
