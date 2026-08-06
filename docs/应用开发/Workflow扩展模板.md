# Workflow 扩展模板

## 1. 边界

Workflow 的 State、节点、条件路由和业务规则属于应用项目。LangGraph 负责逻辑编排，
Temporal 负责持久执行、HumanGate、重试和恢复；Gaia 提供生成模板、受控契约、应用装配、
只读运行证据和测试入口，不提供任意流程的低代码 DSL。

## 2. 生成

在 `gaia init` 创建的项目根目录执行：

```bash
uv run gaia add-workflow contract-review --directory .
```

生成：

```text
src/<application_module>/workflows/contract_review.py
tests/workflows/test_contract_review.py
```

命令拒绝覆盖已有同名 Workflow。名称会规范化为 Python module 名，但公开的 `scenario_id` 仍由
应用在 `ScenarioRunner` 和 Policy 中显式定义。

## 3. 修改顺序

1. 先在 State 中加入业务输入、中间结果和最终结果；
2. 每个节点只承担一个可测试职责；
3. 条件路由返回有限、显式的 route；
4. 为每条 route 增加独立测试；
5. 将副作用转换成 `SideEffectProposal`，不要在 Workflow 节点内直接写客户系统；
6. 由应用的 `ScenarioRunner` 把 Workflow 结果转换为 `RuntimeOutcome`；
7. 在 `RuntimeDependencies.runners` 中注册稳定的 `scenario_id`。

## 4. 验证

```bash
uv run pytest -q tests/workflows
uv run gaia check --config gaia.yaml
```

需要人工确认时返回 Gaia HumanGate 契约，由 Temporal Workflow 等待 Update；需要恢复时依赖
Temporal History 与 Activity Retry，不要在应用内另建恢复扫描器。完整、可运行的接入参考是
`examples/controlled_task`，Worker 使用 `gaia worker --config ... --app ...` 启动。
