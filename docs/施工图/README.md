# 施工图：已完成的实现记录

> **这里不是待办清单。** 本目录记录 Gaia 从早期交付套件走到今天的施工过程——目标、
> 任务卡、验收标准和当时的判断。**全部任务已完成**，其中一部分描述的架构此后又被替换掉了。
>
> 想知道**现在**是什么样，看这三处，不要看本目录：
>
> | 想知道 | 看哪里 |
> | --- | --- |
> | 这个框架是什么、能证明什么、不能证明什么 | [`docs/工程纪实-决策与缺陷.md`](../工程纪实-决策与缺陷.md) |
> | 怎么用 | [`developer-docs/`](../../developer-docs/)（`make dev-docs` 本地预览） |
> | 实际行为 | 代码与测试。冲突时以代码为准 |
>
> 按 [`archive/README.md`](../archive/README.md) 的同一条规矩：**不要编辑这些文件来
> "修正"过时的表述**。它们的价值在于记录当时的判断，改写就毁掉了这个价值。

## 各份施工图的状态

| 施工图 | 状态 |
| --- | --- |
| [00-工程基线](00-工程基线.md)、[01-目标架构与模块边界](01-目标架构与模块边界.md)、[01-公共契约](01-公共契约.md) | 已完成 |
| [02-配置模型与自动装配](02-配置模型与自动装配.md)、[03-GaiaApplication生命周期与Actuator](03-GaiaApplication生命周期与Actuator.md) | 已完成 |
| [02-Runtime状态机与事务边界](02-Runtime状态机与事务边界.md) | **已被取代**：SQL Runtime 整个换成了 Temporal |
| [03-controlled-task黄金场景](03-controlled-task黄金场景.md)、[04-实现任务清单](04-实现任务清单.md) | 已完成 |
| [05-Dev-Console设计](05-Dev-Console设计.md) | 已完成；Console 的演示与证据页此后又重做过，见 18 |
| [06-现有代码迁移图](06-现有代码迁移图.md) | **已被取代**：迁移已完成，图中多数文件已不存在 |
| [07-质量策略与测试矩阵](07-质量策略与测试矩阵.md)、[08-Gaia-Test-Kit设计](08-Gaia-Test-Kit设计.md) | 已完成 |
| [09-Runtime安全边界与Sandbox](09-Runtime安全边界与Sandbox.md) | 已完成；写入边界仍是 `src/gaia/runtime/safety.py` |
| [10-Redis限流与Outbox](10-Redis限流与Outbox.md)、[11-Python原生生命周期与集成边界](11-Python原生生命周期与集成边界.md) | 已完成 |
| [12-Agent研发SOP与流水线](12-Agent研发SOP与流水线.md) | 已完成 |
| [13-重构施工图-装配打通与Runtime拆解](13-重构施工图-装配打通与Runtime拆解.md) | 已完成（工程 A–H）；其中 Runtime 拆解部分随 SQL Runtime 一起被取代 |
| [17-TemporalIO-迁移任务清单](17-TemporalIO-迁移任务清单.md) | 已完成：Temporal 成为唯一执行 provider |
| [18-演示可用性施工图](18-演示可用性施工图.md) | 已完成（D1–D6） |
| [实现状态](实现状态.md) | **历史快照**，停在 Temporal 迁移之前 |

## 仍然成立的硬约束

下面这些不是历史，是现在仍在执行的边界。改动触碰到其中任何一条时，先想清楚再动：

- `src/gaia/runtime/` 不得 import 任何具体示例、Mock 资源或业务 Intent。
- FastAPI lifespan 是根资源作用域，`src/gaia/application/` 管理 Gaia 组件子作用域。
- Dev Console、CLI、YAML 和 API 使用同一个 `GaiaApplicationConfig`，不得各自发明配置结构。
- Dev Console 是独立本地开发进程，不进入生产应用的 Python 包、组件图或 Compose。
- Starter 只提供组件声明、默认配置和 Factory，不直接启动进程或执行 Run。
- `configure()` 不得连接外部系统；application-scoped 资源只能由 `AsyncExitStack` 进入。
- 自动配置必须可解释：每个组件记录来源、实现、配置 Profile、替换点和装配原因。
- 复杂业务逻辑留在应用代码中；可配置不等于把 Workflow、规则和 Adapter 做成低代码。
- `controlled-task` 只是示例，不得成为 Runtime 内置特例。
- 历史 Run 的 `version_bundle` 不因后续配置变更而改变。
- Test Kit 从外部驱动应用测试，不进入 Runtime 的线上请求主链。
- `runtime.environment` 是服务端安全事实；客户端 `RunRequest.mode` 只能匹配，不能切换环境。
- `src/gaia/runtime/safety.py` 是不可绕过的写入边界，改它要有充分理由。
- `GaiaRuntimeWorkflow` 是重放关键代码，改动必须通过
  `tests/integration/test_workflow_replay.py` 的历史回放。

## 质量门禁

```bash
make setup
make verify
```

提交前跑 `make change-ready`：仓库有提交闸门，直接 `git commit` 会被拒。
