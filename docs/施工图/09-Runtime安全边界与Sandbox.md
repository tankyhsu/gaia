# 09 Runtime 安全边界与 Sandbox

## 1. 结论

Gaia 当前实现的是 **Runtime Safety Boundary + Integration Sandbox Profile**，不是任意代码执行
沙箱。没有 ReAct、Code Interpreter、Shell 或浏览器自由执行能力时，不建设容器级 Sandbox 平台。

三类能力必须分开：

| 能力 | 解决的问题 | 当前状态 |
| --- | --- | --- |
| Runtime Safety Boundary | 一次工具调用能否执行 | 已实现，所有环境强制 |
| Integration Sandbox | 执行后最多能影响哪些测试资源 | 已实现配置与 Adapter 环境绑定 |
| Code Execution Sandbox | 任意代码、Shell、文件和网络隔离 | 未实现，当前非目标 |

容器隔离不能替代 Runtime Policy。一个容器如果持有生产 Token，仍然可以修改真实 ERP 或数据库。

## 2. 服务端环境是唯一事实

`runtime.environment` 由服务端 `gaia.yaml`、Profile、环境变量或 CLI 覆盖决定：

```yaml
gaia:
  profile: mock
  runtime:
    environment: mock
  profiles:
    sandbox:
      runtime:
        environment: sandbox
        write_mode: approval_required
    customer:
      runtime:
        environment: customer
        write_mode: disabled
```

`RunRequest.mode` 暂时为兼容性保留，但只作为客户端声明。它必须等于服务端环境，否则在创建 Run
之前返回 `ENVIRONMENT_MODE_MISMATCH`。调用者不能通过把请求写成 `mock` 或 `sandbox` 改变实际
Adapter、凭据或安全策略。

## 3. 环境写入上限

未显式配置 `runtime.write_mode` 时使用以下安全默认值：

| Environment | 默认写入上限 | 含义 |
| --- | --- | --- |
| `mock` | `enabled` | 只允许声明支持 mock 的 Adapter；仍受场景 Policy 和风险规则约束 |
| `sandbox` | `approval_required` | 所有写操作必须 HumanGate；禁止配置为无人审批的 `enabled` |
| `customer` | `disabled` | 默认禁止真实写入，必须由部署配置显式开启 |

最终写入策略取环境上限与场景 `ExecutionPolicy.write_mode` 中更严格的一项。场景只能收紧环境
策略，不能放宽。

## 4. 副作用执行前的固定校验

Workflow 只能产生 `SideEffectProposal`。Runtime 在建立 Command 或调用 Adapter 前依次验证：

1. Runner 的 `ExecutionPolicy.scenario_id` 与请求场景一致；
2. 用户角色属于场景 Policy 的可识别范围；
3. 工具已经显式注册；
4. 工具位于 `ExecutionPolicy.allowed_tools`；
5. 注册的 `ToolDefinition.kind` 是 `write`；
6. 当前服务端环境位于 `ToolDefinition.allowed_environments`；
7. 用户具备 `ToolDefinition.required_roles`；
8. Proposal 风险等级与注册定义完全一致，Workflow 或模型不能降低风险；
9. 环境与场景的有效 `write_mode` 允许写入；
10. 根据有效写入模式和风险决定直接执行或创建 HumanGate。

任一检查失败，Run 进入 `blocked`，写 Adapter 不会实例化。

## 5. Tool 注册是安全边界

写工具必须同时注册定义和 Factory：

```python
WriteToolRegistration(
    definition=ToolDefinition(
        name="update-record",
        version="1.0.0",
        kind="write",
        risk_level="high",
        required_roles=["operator"],
        timeout_seconds=5,
        max_retries=0,
        idempotent=True,
        allowed_environments=["sandbox"],
    ),
    factory=create_sandbox_adapter,
)
```

Factory 返回的 Adapter 定义必须与注册定义完全一致，否则命令失败为
`TOOL_DEFINITION_MISMATCH`。这防止配置审查的是低风险工具，运行时却替换成另一个实现。

应用启动时会检查所有已注册写 Adapter 是否允许当前环境。Sandbox 进程误装 Customer Adapter
或反向误装时，启动立即失败，不等待首次请求。

## 6. Integration Sandbox 的实际隔离

Gaia Core 能强制 Adapter 环境绑定，但以下资源隔离由应用和部署 Profile 提供：

- 独立数据库、Schema、Bucket 或 Namespace；
- 脱敏或合成数据；
- 测试账号、最小权限凭据和独立 SecretRef；
- 客户测试 Endpoint 或 Mock 写 Adapter；
- 出站网络 allowlist；
- 独立模型 Token、调用次数、时间和费用预算。

首个参考应用的 Sandbox 使用真实 Runtime、Policy、HumanGate、数据库和事件链，但写 Adapter 仍
只修改内存 Mock 资源。它证明装配与围栏，不声称模拟了客户网络。

## 7. Adapter 调用与恢复

通过安全校验后，写操作仍必须遵守：

- Command 状态机与数据库 CAS；
- 确定性幂等键；
- 审批与请求者分离；
- Adapter 超时后的 reconcile；
- `executing/unknown` 启动恢复；
- Adapter 构造或执行异常转成 `TOOL_ADAPTER_ERROR`，不得遗留为假成功。

HumanGate 是授权环节，不是隔离环境。审批通过后 Adapter 会真实执行，因此环境和凭据隔离仍是
必要的第二道防线。

## 8. 与 Test Kit 的关系

Gaia Test Kit 可以用同一 Dataset 驱动不同环境：

```text
mock      -> 快速、确定性、无外部资源
sandbox   -> 真实模型/数据库/测试系统的集成测试
customer  -> 少量、显式授权的验收测试
```

Test Kit 决定测什么和如何判断；Runtime Environment 决定被测应用能触碰什么。两者不是两套
Runtime，也不是同一个 Profile。

## 9. 后续触发 Code Execution Sandbox 的条件

只有加入下列能力之一时才单独设计执行沙箱：

- 模型生成并运行 Python、JavaScript 或 Shell；
- ReAct Agent 自主选择开放式工具；
- 文件上传后的动态解析或不可信代码；
- 浏览器自动化访问未知站点；
- 用户自定义插件在进程内执行。

届时需要进程/容器隔离、只读文件系统、网络策略、资源配额、超时销毁和制品扫描。该能力应作为
独立 Starter 或服务，不进入当前 Runtime 的默认依赖。
