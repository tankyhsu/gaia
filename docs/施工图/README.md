# Gaia Framework M1 施工图

## 1. 唯一目标

本目录是 Gaia 从早期交付套件迁移为“AI 应用开发与运行框架”的唯一实现入口。

Gaia M1 必须证明：业务构建者可以从场景模板生成简单 Demo 起点；开发者可以用统一的
`GaiaApplication`、Starter、自动配置和 `gaia.yaml` 装配一个可运行、可检查、可测试的 AI
应用；可选 Gaia Dev Console 在开发环境完成初始化并投影同一套真实配置和运行状态。

实现者按以下顺序阅读：

1. [00-框架定位与工程基线](00-工程基线.md)
2. [01-目标架构与模块边界](01-目标架构与模块边界.md)
3. [02-配置模型与自动装配](02-配置模型与自动装配.md)
4. [03-GaiaApplication生命周期与Actuator](03-GaiaApplication生命周期与Actuator.md)
5. [02-Runtime状态机与事务边界](02-Runtime状态机与事务边界.md)
6. [05-Dev Console 设计](05-Dev-Console设计.md)
7. [06-现有代码迁移图](06-现有代码迁移图.md)
8. [07-质量策略与测试矩阵](07-质量策略与测试矩阵.md)
9. [08-Gaia Test Kit 设计](08-Gaia-Test-Kit设计.md)
10. [09-Runtime 安全边界与 Sandbox](09-Runtime安全边界与Sandbox.md)
11. [10-Redis 缓存、限流与 Outbox](10-Redis限流与Outbox.md)
12. [11-Python 原生生命周期与集成边界](11-Python原生生命周期与集成边界.md)
13. [12-Agent 研发 SOP 与流水线](12-Agent研发SOP与流水线.md)
14. [04-实现任务清单](04-实现任务清单.md)
15. [应用 Workflow 扩展模板](../应用开发/Workflow扩展模板.md)

当前进度和可复现证据见[实现状态](实现状态.md)。

## 2. 规范优先级

发生冲突时按以下顺序裁决：

1. 本施工图定义的框架边界和机器可读测试；
2. `src/gaia/contracts/` 与公开 OpenAPI；
3. `gaia.yaml` 配置模型；
4. 示例应用自己的 `specs/` 与 README；
5. 其他历史设计文档。

旧 `controlled-task` 规格只能约束示例应用，不能反向定义 Gaia 框架公共契约。

## 3. 框架化硬约束

- `src/gaia/runtime/` 不得 import 任何具体示例、Mock 资源或业务 Intent。
- FastAPI lifespan 是根资源作用域，`src/gaia/application/` 管理 Gaia 组件子作用域。
- Dev Console、CLI、YAML 和 API 使用同一个 `GaiaApplicationConfig`，不得各自发明配置结构。
- Dev Console 是独立本地开发进程，不进入生产应用的 Python 包、组件图或开发基础设施 Compose。
- Starter 只提供组件声明、默认配置和 Factory，不直接启动进程或执行 Run。
- `configure()` 不得连接外部系统；application-scoped 资源只能由 `AsyncExitStack` 进入。
- Core、Integration、Capability Pack 和客户 Adapter 必须遵守 11 号施工图的依赖方向。
- 自动配置必须可解释：每个组件记录来源、实现、配置 Profile、替换点和装配原因。
- 复杂业务逻辑留在应用代码中；可配置不等于把 Workflow、规则和 Adapter 做成低代码。
- `controlled-task` 必须作为示例验证框架，不得继续成为 Runtime 内置特例。
- 历史 Run 的 `version_bundle` 不因后续配置变更而改变。
- Test Kit 从外部驱动应用测试，不进入 Runtime 的线上请求主链。
- `runtime.environment` 是服务端安全事实；客户端 `RunRequest.mode` 只能匹配，不能切换环境。

## 4. M1 完成定义

只有以下事实全部成立，才可以声称 Gaia Framework M1 完成：

1. `gaia init` 能生成一个可安装、可运行、可测试的独立应用。
2. `gaia check` 能加载并校验 `gaia.yaml`、Profile、Starter 和组件依赖。
3. `GaiaApplication` 能完成 `created -> configured -> started -> stopped` 生命周期。
4. 至少五类组件通过 Starter 自动装配：Model、Workflow、Context、Tool、Policy。
5. Runtime 不再 import `controlled-task` 或具体 Mock 实现。
6. Actuator 返回应用、配置、组件、健康状态、版本信息和通用 Runtime 运行摘要。
7. Dev Console 的 Quick Start 支持业务场景初始化；其余页面按概览、组件、运行、配置和测试
   组织开发任务，配置只读投影当前生效值与来源。
8. 原有 Runtime、HumanGate、幂等、副作用恢复与 SSE 行为不回归。
9. `controlled-task` 作为示例应用通过原有验收样本。
10. 全部质量门禁和独立子 Agent 验证通过。
11. Runtime 对服务端环境、工具环境、角色、风险、写入上限和 Adapter 定义实施不可绕过校验。
12. Redis 与 Outbox 作为可选 Starter，不成为 Core Runtime 的强制依赖或持久状态捷径。
13. 配置阶段零资源副作用，ASGI lifespan 能对所有 application-scoped 资源逆序释放。

## 5. 全量质量门禁

```bash
cd /path/to/gaia
make setup
make verify
```

真实 PostgreSQL 与 Redis 验证由 GitHub service container 承担。外部模型验证在研发阶段仅允许
开发者显式手工触发，不进入 GitHub 自动流水线。
不得在自动验收中删除本地开发基础设施的数据卷。
