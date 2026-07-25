# 11 Python 原生生命周期与集成边界

## 1. 架构结论

Gaia 借鉴 Spring Boot 的声明式装配体验，不复制 Spring Bean 容器。框架的价值是把成熟库装配成
可配置、可检查、可测试、可治理的 AI 应用，不是重写 Redis、SQLAlchemy、LangGraph 或消息客户端。

代码分为四类边界：

| 层 | 目录 | 拥有什么 | 不拥有什么 |
| --- | --- | --- | --- |
| Core | `application/config/components/contracts/sdk/runtime` | 契约、装配计划、运行围栏 | 厂商 Client 和基础设施算法 |
| Integration | `integrations/` | 成熟第三方库的资源绑定 | 业务规则、Runtime Policy |
| Capability Pack | `capabilities/` | 组合端口与 Integration 的可选行为 | 默认强制主链 |
| Application Adapter | 示例或客户项目 | 客户系统读写与业务映射 | 绕过 Runtime 的授权能力 |

`Adapter` 一词只用于客户系统或运行时端口的实现。Redis、SQLAlchemy 等库接入统一称为
`Integration`，避免把“外部系统业务适配”和“基础设施客户端绑定”混成一层。

## 2. 何时拥有抽象

Gaia 只有满足以下至少一项时才增加公共端口：

1. Gaia Core 或 Runtime 需要依赖稳定语义，而不是厂商 API；
2. 同一能力存在测试替身或多个实现；
3. Gaia 必须统一安全、事务、幂等、TTL、失败或审计语义；
4. Starter 需要为 Actuator、Profile 和测试提供稳定替换点。

如果接口只是逐个转发第三方库方法，而且框架本身不消费该接口，则直接使用成熟库，不增加包装。

当前判断：

| 能力 | 归属 | 理由 |
| --- | --- | --- |
| redis-py Client/Pool | Integration | 成熟客户端，Gaia 只管理配置与资源作用域 |
| `CacheProvider` | 可选 SDK 端口 | 强制 namespace、bytes 与 TTL 语义 |
| `RateLimiter` | 可选 SDK 端口 | 稳定返回额度决策，算法实现可替换 |
| Transactional Outbox | Capability Pack | 绑定 Gaia 事件契约与业务事务语义 |
| Kafka/RabbitMQ Client | 未来 Integration | 需求出现后使用成熟客户端，不进入 Core |

## 3. 配置与运行分离

`GaiaApplication.configure()` 必须是零 I/O、零外部连接的纯装配阶段：

```text
配置加载
  -> Starter 条件
  -> ComponentSpec
  -> 依赖图校验
  -> Actuator 可解释计划
```

只有进入 `GaiaApplication.lifespan()` 才创建组件和打开资源：

```text
FastAPI lifespan
  -> AsyncExitStack
       -> SQLAlchemy session factory
       -> GaiaApplication.lifespan
            -> application-scoped Component Resource
       -> application-owned resources
  -> serve requests
  -> reverse cleanup
```

配置检查因此不会连接 Redis、数据库、模型 Endpoint 或客户系统。每个 ASGI Worker 拥有自己的
连接池和资源作用域，不把 Python 进程内对象误当成跨进程 Singleton。

## 4. ComponentSpec

Starter 只注册组件规格：

- `ComponentDescriptor`：ID、Kind、实现、依赖、配置键、来源和 `scope`；
- 普通 Factory：接收已解析的依赖映射，返回普通对象；
- Resource Factory：返回 `AbstractAsyncContextManager[T]`；
- `ComponentRegistry`：验证 DAG，按拓扑顺序构建，交给 `AsyncExitStack` 逆序释放。

`scope=static` 表示对象没有需要框架释放的资源；`scope=application` 表示资源与一次应用 lifespan
绑定。框架不得通过 `hasattr(component, "start")` 猜测生命周期。

## 5. Starter 边界

Starter 可以：

- 提供默认配置和装配条件；
- 检查可选依赖是否安装；
- 注册 ComponentSpec 和依赖；
- 暴露 Actuator 元数据。

Starter 不可以：

- 在 `contribute()` 中连接外部系统；
- 启动线程、Consumer 或 Run；
- 复制第三方库的完整 API；
- 包含客户业务规则；
- 隐式创建用户不可见的后台任务。

`cache-redis` 和 `rate-limit-redis` 都依赖一个 application-scoped `redis-client`。该 Client 在
资源进入时 `PING`，退出时 `aclose()`；Cache 和 RateLimiter 只实现 Gaia 选择保留的语义。

## 6. 依赖方向

```text
application/api/cli -> starters -> integrations/capabilities
application -> components/config
capabilities -> sdk + persistence/integrations
integrations -> sdk/config
runtime -> sdk/contracts
```

禁止：

- `sdk/contracts/runtime -> integrations/capabilities`；
- `integrations -> application/starters/runtime/capabilities`；
- `capabilities -> application/api/starters`；
- Core 出现客户或行业常量；
- 恢复旧 `gaia.adapters.redis` 这类基础设施混合目录。

这些方向由 `tests/architecture/test_boundaries.py` 固化。

## 7. 验收

- `configure()` 后 component mapping 为空且没有资源副作用；
- `lifespan()` 内组件可用，退出后资源逆序释放；
- 后置资源进入失败时，先前资源仍会释放；
- Factory 能读取 `depends_on` 对应的真实实例；
- Redis Cache 与 RateLimiter 共享同一个 redis-py Client；
- FastAPI、应用资源和数据库位于同一个 ASGI 根资源作用域；
- Core/Integration/Capability 依赖方向通过架构测试。
