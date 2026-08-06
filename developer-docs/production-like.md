# 本地 Production-like 验证

这套 Docker Compose 用于验证 Gaia 的生产拓扑与故障语义，不是高可用生产部署模板。

## 它启动什么

- 两个 Gaia API，由 Nginx gateway 负载均衡；
- 两个 Gaia Temporal Worker，共享一个 task queue；
- Temporal Server、独立 PostgreSQL 和 Temporal UI；
- Gaia operational PostgreSQL；
- Langfuse Web/Worker、PostgreSQL、ClickHouse、Redis 和 MinIO；
- 静态构建的 Gaia Console。

三个数据所有者彼此独立：Temporal PostgreSQL 保存 Workflow History，Gaia PostgreSQL 保存
应用与无正文观察数据，Langfuse stores 保存 Trace/Token/成本。

## 运行

Docker Desktop 建议至少分配 8 GB 内存。首次启动需要下载镜像和构建 Gaia/Console：

```bash
make prod-up
make prod-acceptance
make prod-down
```

访问地址：

| 服务 | 地址 |
| --- | --- |
| Gaia Console | `http://127.0.0.1:4180` |
| Gaia API gateway | `http://127.0.0.1:8088` |
| Temporal UI | `http://127.0.0.1:8080` |
| Langfuse | `http://127.0.0.1:3000` |

本地 Langfuse 用户是 `gaia@example.local`，密码
`gaia-production-like-password`。这些是公开的本地测试凭据，不能用于共享环境。

复制 `infra/production-like/.env.example` 为 `.env` 可以覆盖默认值：

```bash
cp infra/production-like/.env.example infra/production-like/.env
```

Compose 自动读取与 compose 文件同目录的 `.env`。

## 验收证明什么

`make prod-acceptance` 执行黑盒故障实验：

1. 创建一个停在 HumanGate 的 sandbox Run；
2. 同时停止两个 Worker，再只启动其中一个；
3. 对原 Gate 审批并验证 Workflow 成功恢复；
4. 停止一个 API，验证 gateway 仍能查询同一 Run；
5. 重启 Temporal Server，验证 PostgreSQL History 可恢复；
6. 验证 Gaia `/v1/runs` 审计投影在 Worker 和 Temporal 重启后仍列出 Run；
7. 验证 Langfuse 能按 Temporal run ID 查询 Trace。

脚本不会销毁数据。`make prod-down` 停止容器并保留 volumes；需要完全重置时运行：

```bash
docker compose -f infra/production-like/compose.yaml down -v --remove-orphans
```

## 它不能证明什么

- 多可用区、Kubernetes 调度和真实负载均衡；
- Temporal mTLS、Authorizer、生产 namespace 治理和备份 SLA；
- Langfuse 的 HA、备份和大规模 ClickHouse 容量；
- 企业 IdP、证书轮换和客户网络策略；
- 客户 Adapter 在真实下游系统中的幂等与对账。

Temporal 官方将 Compose 定位为本地开发/测试，生产推荐 Helm 和独立 schema 管理；Langfuse
也将本地 Compose 定位为测试与低规模部署。这里的 `production-like` 表示组件边界和故障语义
接近生产，而不是把单机 Docker 包装成生产 SLA。

Gaia 的正式生产默认是 Helm/Kubernetes，而不是这套 Compose。运行方式之间的关系见
[选择运行与部署方式](runtime-profiles.md)；Chart 和外部依赖操作见仓库内
`infra/production-like/helm/README.md`。
