# controlled-task 旧黄金场景迁移说明

本文件不再是 Gaia Framework 的实现规范。

原黄金场景的 Intent、资源、组织、规则、Workflow、Mock Adapter、验收样本和 Demo 应迁移到
`examples/controlled_task/`，作为验证 Starter、自动配置、Runtime 围栏和评测能力的参考应用。

迁移完成前，历史细节可通过 Git 提交 `afde716` 查阅。新的权威要求见：

- [目标架构与模块边界](01-目标架构与模块边界.md)
- [现有代码迁移图](06-现有代码迁移图.md)
- [实现任务清单 T04](04-实现任务清单.md)

任何实现者不得再从本文件为 `src/gaia/` 增加 controlled-task 特例。
