# HTTP API

Gaia 的 HTTP 接口由 FastAPI 根据路由、类型标注和 Pydantic 模型自动生成 OpenAPI。

本地启动应用后：

- [Swagger UI](http://localhost:8000/docs)：交互式查看和调用接口；
- [ReDoc](http://localhost:8000/redoc)：适合连续阅读；
- [OpenAPI JSON](http://localhost:8000/openapi.json)：用于生成多语言 Client。

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
Client 只负责协议调用，业务规则和 Gaia Runtime 不复制到调用方。

Guardrail 决策查询：

```http
GET /v1/runs/{run_id}/guardrail-decisions
```

响应包含阶段、规则 ID/版本、动作、风险分、原因码和耗时。`input_ref` / `output_ref` 是内容
哈希引用，不是业务正文。

开发期 Prompt 工作区状态：

```http
GET /devtools/prompts
```

仅在 `GAIA_DEVTOOLS_ENABLED=true` 时注册。响应明确区分 `disabled`、`file` 和 `postgres`；
文件模式只返回 Artifact 标识、版本、相对路径和内容哈希，不返回 Prompt 正文。
