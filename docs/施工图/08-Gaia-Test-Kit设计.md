# 08 Gaia Test Kit 设计

## 1. 定位

Gaia Test Kit 是 AI 应用的开发期测试框架，角色类似传统应用中的 `starter-test`。它不把 Gaia
变成评估平台，也不规定客户必须采用某一种统计方法。它只提供稳定的测试骨架：

```text
版本化 Dataset
  -> CaseExecutor 执行被测应用
  -> Evaluator 产生逐案例 Measurement
  -> QualityGate 根据完整证据做通过/失败决策
  -> TestReport 保存版本、结果和失败原因
```

Runtime 负责产生可追踪的运行结果和证据；Test Kit 从外部驱动 Runtime 或应用接口。测试组件不得
进入线上请求主链，也不得成为 `GaiaApplication` 启动的前置条件。

## 2. 第一版能力边界

第一版只提供：

- 版本化 `TestDataset` 和唯一 `case_id`；
- JSON/YAML Dataset Loader；
- 可替换的 `CaseExecutor`、`Evaluator`、`QualityGate` 协议；
- 一个顺序执行、可设置重复次数的 `GaiaTestKit`；
- 结构化 Observation、Measurement、GateResult 和 TestReport；
- 一个结构化结果子集断言和“显式失败即阻断”的默认 Gate；
- 一个支持 Case 阈值、Suite 通过率、关键 Case 和标签分组的通用 `PassRateGate`；
- 执行器、Evaluator、Gate 异常隔离及失败证据；
- 记录被测对象、Dataset、Evaluator 和 Gate 版本。

第一版明确不提供：

- 固定的置信区间、Bootstrap、显著性检验或贝叶斯模型；
- 内置 LLM-as-judge、RAGAS 或某个厂商评估服务；
- 在线流量实验、生产反馈学习和大型评估看板；
- 代替 Pytest 的测试发现、Mock、断言和覆盖率能力；
- 把一个综合分数包装成业务正确性的结论。

## 3. 四类扩展契约

### 3.1 TestDataset

Dataset 是可审计的测试输入，而不是一份临时 Prompt 列表。每个 Dataset 固定：

- `dataset_id` 与 `version`；
- 案例输入、期望、标签和应用自有 metadata；
- 唯一且稳定的 `case_id`。

Dataset 如何分层、采样和维护属于应用项目。Gaia 只校验结构并在报告中固定版本。
`load_dataset(path)` 支持 `.json`、`.yaml` 和 `.yml`，允许文件直接保存 Dataset，也允许使用
`dataset:` 作为唯一顶层键。

### 3.2 CaseExecutor

`CaseExecutor` 把一个 TestCase 交给被测对象并返回 TestObservation。应用可以实现为：

- 直接调用 Python 应用服务；
- 通过 HTTP 调用正在运行的 Gaia 应用；
- 驱动当前 `ReplayRunner` 的确定性场景回放；
- 调用真实模型、RAG 或外部 Agent 平台。

Observation 包含实际结果、Trace/引用/Run ID 等 evidence、错误码、耗时和重复序号。

### 3.3 Evaluator

Evaluator 只负责把一个 Case 与一次 Observation 转成一个或多个 Measurement。它可以是：

- Schema、权限、工具参数和状态机等确定性断言；
- 文本相似度、检索命中、延迟或成本指标；
- 应用自定义规则或业务专家评分；
- 外部 LLM judge；
- 用户自己的统计模型输出。

Gaia 不解释自定义指标的业务含义。Evaluator 必须提供稳定 ID 和版本，异常会进入报告并由默认
Gate 阻断，不能被吞掉。

### 3.4 QualityGate

Gate 接收完整 Dataset、所有 Observation、Measurement 和被测对象版本，再决定是否通过。因此
用户可以实现简单阈值、分层规则、基线对比、置信区间或其他任意模型，而 Gaia 无需内建这些数学
假设。Gate 同样必须有 ID 和版本。

## 4. 默认策略

Gaia 默认只做保守且可解释的事情：

1. `ExpectedSubsetEvaluator` 检查结构化实际结果是否包含案例声明的期望字段；
2. `RequiredMeasurementsGate` 在执行错误、Evaluator 错误或任一显式 `passed=false` 时失败；
3. `passed=null` 只代表观测指标，不由默认 Gate 擅自判断好坏；
4. 没有 Evaluator、没有 Gate、空 Dataset、重复 ID 均直接拒绝运行。

`PassRateGate` 是显式选择的发布 Gate，不会自动加载。它把一次或多次 Measurement 聚合成
Case 结果，再计算 Suite 通过率；缺失 Measurement 不会被当成失败样本悄悄稀释，而是单独记录并
阻断。它还可以要求：

- 带 `critical` 等标签的案例必须全部通过；
- `boundary`、`safety` 等标签分组分别达到阈值；
- Dataset 至少包含指定数量的案例；
- 重复执行按 `all`、`any` 或数值均值聚合。

## 5. Golden Dataset

Gaia 将 Golden Dataset 视为应用仓库里的受审测试资产，而不是框架内置数据。推荐维护：

- `smoke`：提交代码时运行的少量确定性案例；
- `release-golden`：发版前运行的代表性和边界案例；
- `incident-regression`：来自验收或生产事故、经人工确认后固化的案例。

每个 Case 使用稳定 `case_id`，用 `tags` 表示切片和风险，用 `metadata` 保存脱敏来源、维护状态、
Rubric 版本等治理信息。示例见 `examples/testing/release-golden.yaml`。

```python
dataset = load_dataset(Path("tests/datasets/release-golden.yaml"))
gate = PassRateGate(
    evaluator_id="application-judge",
    metric="answer_quality",
    case_threshold=4.0,
    suite_threshold=0.95,
    critical_tags=("critical",),
    slice_thresholds={"boundary": 0.90, "safety": 1.0},
)
report = await GaiaTestKit(
    executor,
    evaluators=(judge,),
    gates=(RequiredMeasurementsGate(), gate),
).run(dataset, subject={"version": "candidate"})
```

`100~200` 是常见起步规模，不是 Gaia 的硬限制。应用负责案例入选、脱敏、人工复核、版本变更和
Holdout 策略。框架不把综合通过率解释成业务正确性或统计置信度。

## 6. 自定义质量模型

应用自己的建模只需要实现 `QualityGate`，不需要修改 Gaia：

```python
class ApplicationQualityGate:
    gate_id = "application-quality"
    gate_version = "2026-07-23"

    async def evaluate(self, context: GateContext) -> GateResult:
        score = my_model(context.dataset, context.results)
        return GateResult(
            gate_id=self.gate_id,
            gate_version=self.gate_version,
            passed=score.accepted,
            reasons=tuple(score.reasons),
            details=score.model_dump(),
        )
```

框架只要求结果可序列化、版本可追踪、失败可定位。模型用均值、分位数、配对检验、置信区间或
人工规则，完全由应用和业务风险决定。

## 7. 与现有 Replay 的关系

现有 `/v1/evals/replays` 和 `ReplayRunner` 继续作为兼容能力存在。它验证固定场景的状态、错误码、
步骤、规则引用、副作用与幂等，是确定性 Acceptance Test，不等同于完整的模型质量评估。

后续以 Adapter 将 Replay 接入 `CaseExecutor`，而不是让 Test Kit 依赖具体示例结构。第一版不为
统一命名而重写已验证的 Replay 持久化和 HTTP 契约。

## 8. 后续演进条件

只有真实应用出现共同需求后才增加：

- Pytest fixture；
- `gaia test` CLI、报告落库和 Dev Console 只读投影；
- cassette record/replay；
- baseline/candidate 配对比较的可选 Gate；
- 外部 judge 和评估平台 Adapter；
- 并发、速率限制和预算控制。

统计工具应作为可选扩展包出现，不能成为 Gaia Core 的依赖。

## 9. 与 DSPy Assert/Suggest 思想的关系

DSPy 早期的 `Assert/Suggest` 把硬约束和软评价带入生成循环；当前 DSPy 文档说明它们已由
`Refine/BestOfN` 取代。Gaia 借鉴机制，不绑定 DSPy API：

- 硬约束对应 `Measurement.passed=true/false`；
- 软指标对应 `passed=null + value/details`；
- Test Kit 负责跨 Dataset 记录与判断；
- 未来可选 `RefinementPolicy` 才负责一次 Run 内的候选生成、反馈和有限重试。

Refinement 不得用于修正权限、审批、数据隔离、缺少可靠依据或已经发生的副作用。任何生成期重试
必须发生在写操作之前，并受次数、Token、时间和费用预算限制。它改善单次候选，不替代版本级
Dataset、基线比较或统计不确定性分析。
