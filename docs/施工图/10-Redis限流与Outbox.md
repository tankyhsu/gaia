# 10 Redis 缓存、限流与 Transactional Outbox

## 1. 结论

Gaia 将 Redis 与消息能力作为可选基础设施，不作为 Core Runtime 的启动前提：

| 能力 | 当前实现 | 不承担 |
| --- | --- | --- |
| Cache | `CacheProvider` + `cache-redis` | Run、审计、长期记忆 |
| Rate Limit | `RateLimiter` + `rate-limit-redis` | Policy 授权、费用结算事实 |
| Outbox | PostgreSQL/SQLAlchemy Outbox | 消息业务处理本身 |
| Publisher | `InProcessEventPublisher` | 跨进程可靠传输 |
| MQ Adapter | 尚未实现 | 不提前绑定 Kafka/RabbitMQ |

Redis Streams 不同时充当缓存、工作队列和可靠事件总线。

Redis 不由 Gaia 重写。`integrations/redis.py` 使用官方 redis-py asyncio Client，只增加 Gaia
选择保留的 namespace、TTL 与额度决策语义。Outbox 位于 `capabilities/outbox.py`，因为它是组合
事件端口与 operational store 的可选行为，不是持久化 Client。

## 2. Redis 配置

```yaml
gaia:
  starters:
    - cache-redis
    - rate-limit-redis
  redis:
    url:
      env: GAIA_REDIS_URL
    key_prefix: gaia
    max_connections: 20
    socket_timeout_seconds: 2
    health_check_interval_seconds: 30
  cache:
    provider: redis
    default_ttl_seconds: 300
    max_ttl_seconds: 86400
  rate_limit:
    provider: redis
```

`redis.url` 使用 `SecretRef`，Actuator 只显示引用。两个能力 Starter 都依赖
`redis-client`：每个应用 Worker 只创建一个共享 redis-py Client，进入 application lifespan 时
执行 `PING`，退出时 `aclose()`。Cache 和 RateLimiter 本身不拥有连接生命周期。

选择了 Redis Starter 但没有安装 `gaia-framework[redis]` 时，配置阶段返回
`CONFIG_OPTIONAL_DEPENDENCY_MISSING:redis`，但不会尝试连接 Redis。

## 3. CacheProvider

```python
class CacheProvider(Protocol):
    async def get(self, namespace: str, key: str) -> bytes | None: ...
    async def set(
        self,
        namespace: str,
        key: str,
        value: bytes,
        *,
        ttl_seconds: int | None = None,
    ) -> None: ...
    async def delete(self, namespace: str, key: str) -> bool: ...
```

约束：

- Key 自动加入 `key_prefix:cache` 与 namespace，用户片段进行百分号编码；
- 每个值必须有 TTL，默认值和最大值由配置约束；
- Provider 只保存 bytes，不替应用选择 JSON、Pickle 或领域序列化；
- Cache miss 和 Redis unavailable 必须区分，后者抛错；
- Run、Command、Gate、Outbox、审计和长期记忆不得只写入 Cache。

## 4. RateLimiter

```python
decision = await limiter.consume(
    "model",
    user_id,
    limit=20,
    window_seconds=60,
    cost=1,
)
```

当前 Redis 实现使用 Lua 将 `INCRBY + EXPIRE` 放在同一原子操作中，返回：

- `allowed`；
- `limit`；
- `remaining`；
- `observed`；
- 被拒绝时的 `retry_after_seconds`。

首版固定窗口适合模型调用次数、并发入口前的请求配额和开发环境保护。精确费用、Token 账单和
跨窗口统计仍应写入持久事实源。以后可以增加 Token Bucket 实现，但不改变 `RateLimiter` 端口。

## 5. Outbox 表与事务边界

`outbox_events` 与业务数据位于同一个 operational PostgreSQL：

```text
业务事务
  ├── 更新 Run / Command / 应用表
  └── INSERT outbox_events(status=pending)
COMMIT

Dispatcher
  ├── SELECT ... FOR UPDATE SKIP LOCKED
  ├── 写入 worker lease，attempts + 1
  ├── Publisher.publish(event)
  └── published / retry / dead_letter
```

`enqueue()` 接受调用方现有 `AsyncSession`，自身只 `flush`，绝不提交。业务事务回滚时 Outbox 事件
一起消失，因此不会出现“数据库失败但消息已经发出”。

## 6. 投递与失败语义

- 投递是 **at least once**，不是 exactly once；
- Handler 必须使用 `event_id` 或业务键实现幂等；
- PostgreSQL 使用行锁与 `SKIP LOCKED` 支持多个 Dispatcher 并发领取；
- 领取后写入 `locked_by/locked_until`，进程崩溃后租约到期可重领；
- 失败按 `retry_delay_seconds` 重试；
- 达到 `max_attempts` 转为 `dead_letter`，保留最后错误；
- Publisher 成功、标记 published 前进程崩溃时可能重复投递，这是至少一次语义的一部分。

SQLite 可用于本地单进程测试，但多 Worker 并发正确性以 PostgreSQL 为准。

## 7. 进程内 Publisher

`InProcessEventPublisher` 支持按 topic 和 `*` 注册异步 Handler。它适用于：

- 单进程开发和集成测试；
- Outbox 契约验证；
- 尚未选定企业消息平台时保持应用代码稳定。

它不提供跨进程传输、Broker 持久化或 Consumer Group。`OutboxDispatcher` 当前由应用或进程内
调度器调用 `dispatch_once()`；Gaia 不偷偷启动一个用户不可见的后台线程。

## 8. MQ Adapter 触发条件

出现以下需求后再实现首个 MQ Starter：

- API 与 Worker 需要分进程、分实例部署；
- Outbox 事件需要跨系统消费；
- Evaluation 或长耗时模型任务需要可靠任务队列；
- 企业已有统一消息平台并要求接入。

选型规则：

| 首要需求 | 首选 |
| --- | --- |
| 企业事件平台、事件流、较高吞吐、已有 Kafka 运维 | Kafka |
| 工作队列、逐任务 ACK、路由和重试、已有 RabbitMQ | RabbitMQ |

未来实现统一 `EventPublisher` Integration，不修改 Outbox 表和业务事务写入方式。MQ 客户端、Consumer
运行时和 Broker 部署都不进入 Gaia 默认依赖。

## 9. 验收证据

- Unit：Key namespace、TTL 上限、固定窗口决策和参数校验；
- Starter：optional extra、默认配置、SecretRef、共享 Client 与 application scope；
- SQLite：事务提交/回滚、重试、死信和租约；
- Redis：真实 TTL 与原子限流；
- PostgreSQL：Alembic `0005`、并发 `SKIP LOCKED`、无重复领取和成功发布；
- 生成项目：Redis extra、PostgreSQL Outbox 依赖和进程内 Publisher 自动补齐。
