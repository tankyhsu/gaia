# ADR 0002：Prompt 是不可变 Artifact

- 状态：已接受
- 日期：2026-07-23

## 背景

业务 Prompt 可能频繁调整。把它当普通配置原地覆盖，会使运行结果无法复现；把编辑能力塞进生产
Runtime，又会重新引入已经移除的通用配置控制面。

## 决定

Core 定义 `PromptRef`、`PromptArtifact` 和 `PromptProvider`。Artifact 由 Prompt ID、精确版本、
消息、输入 Schema、模型要求、元数据和内容哈希组成。Provider 解析精确版本，不负责隐式选择
优先级。

M1 提供 `prompt-file`：文件位于 `<root>/<prompt_id>/<version>.yaml`，适合 GitOps 和本地开发。
Provider 仅在显式 `resolve()` 时读取文件，Starter 装配和 `gaia check` 不产生文件 I/O。

M2 再提供数据库 Registry、环境发布指针、质量门禁与回滚。已发布内容不得原地修改，Run 创建时
固定精确版本和内容哈希。

## 后果

Prompt 创作可以频繁，运行证据仍可复现。文件和数据库 Provider 不隐式混用；生产 Runtime 不暴露
任意 Prompt 编辑入口。
