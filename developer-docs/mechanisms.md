# 内部机制

这部分解释 Gaia 为什么能提供统一的开发体验。应用开发不需要先理解这些实现。

## 配置与自动装配

配置按以下优先级合并：

1. Pydantic 默认值；
2. Starter 默认值；
3. `gaia.yaml`；
4. 当前 Profile；
5. `GAIA__SECTION__KEY` 环境变量；
6. CLI `--set`。

最终配置会记录每个字段的来源。Starter 根据属性、Profile 和可用依赖计算组件图；Actuator 和
Dev Console 展示的是计算结果，而不是另一份配置。

配置文件本身由 `--config`、`GAIA_CONFIG_PATH` 或默认 `gaia.yaml` 选择；它不属于
`GAIA__SECTION__KEY` 配置字段覆盖。`prompt.root` 和 `rag.root` 等应用资产目录相对于配置文件
所在目录解析，因此测试、CLI 和服务进程可以从不同 CWD 启动。

## Python 原生生命周期

`GaiaApplication` 使用 `AsyncExitStack` 管理 application-scoped 资源：

```text
读取配置
  -> 计算 Starter 和 ComponentSpec
  -> 校验依赖图
  -> 按顺序创建资源
  -> 启动 Runtime
  -> 接收请求
  -> 反向释放资源
```

导入模块和 `configure()` 阶段不建立网络连接。资源创建失败时，已经打开的资源会被回滚。
停止后的 Application 实例不会重新进入生命周期；应用入口提供工厂，由测试和需要隔离生命周期的
调用方创建新实例。

## 唯一 Runtime

简单函数、Pipeline 和 LangGraph 最终都适配到 `ScenarioRunner`。Gaia 不为简单场景建立一条
绕开 Policy、幂等和审计的快速通道。

一次 Run 会固定：

- Scenario、Workflow 和规则版本；
- Prompt 精确版本与内容哈希；
- 模型 Profile；
- Toolset 和 Context Profile。

## 写入与 HumanGate

Scenario 只能提出 `ScenarioSideEffect`，不能直接执行业务写入。Runtime 校验环境、角色、工具
白名单、风险和写入模式后，决定拒绝、创建 HumanGate 或执行。

写工具必须提供 `reconcile`。当外部系统超时或进程中断时，Runtime 先确认操作是否已经完成，
避免盲目重试造成重复写入。

## Prompt 与 RAG

Prompt 发布只移动环境指针。新 Run 使用新版本，已经存在或等待审批的 Run 继续使用固定的旧版本。

Dev Console 的 Prompt 入口始终存在：未装配 Provider 时展示选择状态，`prompt-file` 只读列出
版本化 Artifact，`prompt-postgres` 才提供 Draft、验证、发布和回滚。开发工作区未开启时不会
注册写路由，Console 也不会把 404 解释成 Prompt 数据不存在。

RAG 摄取以内容、Parser 和 Chunker 版本生成代际。检索只读取 active generation，并在返回结果前
应用租户、角色和用户权限，Citation 保存文档版本、Chunk、位置和授权依据。

## 测试与观测

Test Kit 支持确定性断言、数据集回放、自定义 Evaluator 和通过率 Gate。生产 Runtime 记录 Run、
事件、模型用量、延迟、重试和错误，但默认不保存模型私有思维链。

ModelGateway 同时提供结构化响应和增量流式响应。Run Event SSE 负责运行状态续传，
`ModelProvider.generate_stream()` 负责模型正文增量，两者不是同一个协议。

Guardrail Pipeline 覆盖输入、检索结果、模型输出、工具参数和工具结果五个执行边界。规则由
应用提供，框架不内置行业词表。每次判断可以生成不含正文的版本化决策证据，并明确配置
防护组件故障时是 `fail_closed` 还是 `fail_open`。完整接入见[安全防护](guardrails.md)。

多 Agent 仅提供受限 Handoff：路由必须显式声明、共享状态由应用拥有、交接次数有硬预算。
开放式 ReAct、任意工具自治和代码执行仍不属于这一模式。
