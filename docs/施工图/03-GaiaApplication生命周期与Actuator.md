# 03 GaiaApplication 资源作用域与 Actuator

## 1. 状态

```text
created -> configured -> starting -> started -> stopping -> stopped
                         \-> failed
```

状态只能前进。失败或停止后的同一实例不能再次启动。`start()/stop()` 保留为显式控制接口，
FastAPI 和应用代码优先使用 `GaiaApplication.lifespan()`。

## 2. 配置阶段

```python
context = await application.configure()
```

`configure()` 只负责：

- 解析配置、Profile 和 Starter 默认值；
- 生成 ComponentSpec；
- 校验依赖缺失与循环；
- 生成 auto-configuration report；
- 建立脱敏配置与组件图快照。

它不得打开数据库、Redis、HTTP Client、模型或客户系统连接。configured Context 的
`components` 为空，组件计划通过 `descriptors` 和 Actuator 展示。

## 3. 运行阶段

```python
async with application.lifespan() as context:
    component = context.components["component-id"]
```

`GaiaApplication` 为每次运行作用域创建一个 `AsyncExitStack`。Registry 按依赖图构建组件：

- 普通 Factory 接收已解析依赖映射并返回无托管资源的对象；
- Resource Factory 返回 `AbstractAsyncContextManager[T]`；
- 进入失败时，已经进入的资源自动逆序释放；
- 退出 lifespan 时，所有 application-scoped 资源自动逆序释放。

框架不检查对象是否碰巧存在 `start()` 或 `stop()` 方法，也不复制 Spring Bean 生命周期回调。

## 4. ASGI 根作用域

FastAPI lifespan 是进程内资源的唯一根节点：

```text
FastAPI lifespan
  -> SQLAlchemy session factory resource
  -> GaiaApplication.lifespan
  -> application-owned lifespan
  -> Runtime recovery
  -> serve
  -> reverse cleanup
```

数据库、Gaia 组件和示例应用资源由同一个 `AsyncExitStack` 管理。每个 ASGI Worker 各自创建资源，
不假设 Python 对象能跨 Worker 共享。

## 5. ApplicationContext

Context 是不可变快照：

- `config` 与 `config_hash`；
- `descriptors` 与 `component_graph_hash`；
- `components`：仅在 started 作用域内包含真实实例；
- `auto_configuration_report`；
- `framework_version` 与 `application_version`；
- `started_at`。

应用代码可以在 started 作用域内通过
`application.get_component("component-id")` 获取已装配实例。该公开入口在应用未启动、已经停止
或组件不存在时明确失败；业务代码不得依赖 `_context` 等内部字段。

退出 lifespan 后组件映射被清空，防止应用继续使用已关闭的资源。配置变更不会热替换正在运行的
Context；需要创建新进程或新应用作用域。

## 6. 执行接入

`TemporalRuntimeEngine` 是 API 到 Temporal 的窄适配器，通过显式
`RuntimeDependencies` 接收 ScenarioRunner、Tool Registry、安全环境和写入上限。
`gaia worker --config ... --app ...` 进入与 API 相同的 application lifespan，并把这些
依赖注册成 Workflow/Activity Worker；任何一侧都不得从全局对象重新装配第二套依赖。

应用自己的 checkpoint、memory、HTTP Client 等资源提供 lifespan。LangGraph 只负责逻辑
步骤，Temporal 持有执行历史、HumanGate、重试和恢复。

## 7. Actuator API

| Endpoint | 内容 | 是否认证 |
| --- | --- | --- |
| `GET /actuator/info` | 应用、框架、Profile、启动时间、hash | M1 本地可匿名 |
| `GET /actuator/health` | 应用与组件健康 | M1 本地可匿名 |
| `GET /actuator/components` | 组件、scope、依赖、装配原因、替换点 | 需要 API Key |
| `GET /actuator/config` | 脱敏配置、environment、write mode、字段来源 | 需要 API Key |
| `GET /actuator/conditions` | positive/negative auto-config report | 需要 API Key |
| `GET /actuator/runtime` | Run、耗时、HumanGate、错误、Outbox 与数据库争用摘要 | 需要 API Key |

Actuator 只读，不承担配置发布。

## 8. 健康语义

- `UP`：应用 started，required 组件健康；
- `DEGRADED`：应用可用，但 optional 组件失败；
- `DOWN`：required 组件失败或应用未 started；
- `UNKNOWN`：组件没有健康检查。

`gaia check` 不通过网络健康探测，保持零外部副作用。`gaia doctor` 是显式诊断命令，负责连接
已启用的数据库、Redis、模型和 embedding Endpoint；运行中的 required 模型健康会反映到
readiness，失败时返回 HTTP 503。
