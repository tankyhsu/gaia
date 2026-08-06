# Gaia 全景图

这张图面向第一次接触 Gaia 的应用开发者、平台工程师和架构师。先看全局，再按需深入。

## 一句话定位

Gaia 是 AI 业务应用的**受控执行层**：上接用户、模型和业务流程，下接工具与业务系统，中间负责身份、策略、审批、持久运行和证据。

## 全景图

<section class="gaia-architecture" aria-label="Gaia 系统全景架构">
  <header><span>GAIA SYSTEM MAP</span><strong>从人发起目标，到业务动作留下证据</strong></header>
  <div class="gaia-lane gaia-lane--people">
    <h3>使用者</h3>
    <div><article><strong>业务用户</strong><small>提出目标</small></article><article><strong>审批人</strong><small>决定高风险动作</small></article><article><strong>运维 / 审计</strong><small>观察与追溯</small></article></div>
  </div>
  <div class="gaia-lane gaia-lane--entry">
    <h3>应用入口</h3>
    <div><article><strong>你的产品界面</strong><small>业务体验</small></article><article><strong>Gaia Console</strong><small>运行、审批、证据</small></article><article><strong>Gaia API</strong><small>统一受控入口</small></article></div>
  </div>
  <div class="gaia-lane gaia-lane--control">
    <h3>Gaia 控制面</h3>
    <div><article><strong>身份与归属</strong><small>谁在操作谁的资源</small></article><article><strong>Run 生命周期</strong><small>创建、幂等、状态</small></article><article><strong>策略与工具准入</strong><small>什么动作可以发生</small></article><article><strong>Human Gate</strong><small>副作用前人工确认</small></article><article><strong>证据投影</strong><small>可查询的执行事实</small></article></div>
  </div>
  <div class="gaia-lane gaia-lane--runtime">
    <h3>编排与执行</h3>
    <div><article><strong>In-process Runtime</strong><small>单进程短流程</small></article><article><strong>Temporal + Worker</strong><small>分布式等待、重试、恢复</small></article><article><strong>LangGraph</strong><small>计算逻辑下一步</small></article></div>
  </div>
  <div class="gaia-lane gaia-lane--business">
    <h3>业务扩展</h3>
    <div><article><strong>场景 / 流程</strong><small>业务步骤</small></article><article><strong>模型 / Prompt</strong><small>理解与生成</small></article><article><strong>工具适配器</strong><small>连接客户系统</small></article></div>
  </div>
  <footer><span>审计存储</span><span>执行历史</span><span>Tracing / Metrics</span><span>客户业务系统</span></footer>
</section>

## Gaia 模块分工

上面的图说明 Gaia 在整个业务系统中的位置。下面这张图只展开 Gaia
自身，回答代码和职责应该放在哪一层：

<div class="gaia-module-map" role="img" aria-label="Gaia 五层模块分工">
  <section><span>01</span><h3>接入层</h3><p>Run / Gate / Evidence API</p><p>认证与组织上下文</p></section>
  <section class="gaia-module-map__control"><span>02</span><h3>控制层</h3><p>Run 生命周期与幂等</p><p>策略、准入与人工 Gate</p><p>证据查询与审计投影</p></section>
  <section><span>03</span><h3>编排层</h3><p>Runtime 接口</p><p>In-process / Temporal Runtime</p><p>Worker / LangGraph</p></section>
  <section><span>04</span><h3>业务扩展层</h3><p>场景与模型 Profile</p><p>工具定义与注册</p><p>客户系统适配器</p></section>
  <section><span>05</span><h3>基础设施层</h3><p>审计与执行历史</p><p>Tracing / Metrics</p><p>客户业务系统</p></section>
</div>

| 模块 | 核心职责 | 业务项目通常怎样扩展 |
| --- | --- | --- |
| 接入层 | 验证调用者，提供 Run、Gate 和证据 API | 接入企业身份，开发自己的产品界面或客户端 |
| 控制层 | 管理 Run、幂等、授权、策略、审批和审计投影 | 配置角色、风险、工具许可和审批规则 |
| 编排层 | 单进程内完成短流程，或把关键流程变成可等待、可恢复的分布式执行 | 选择 in-process 或 Temporal，不为每个业务复制 Runtime |
| 业务扩展层 | 定义场景、模型和真正访问客户系统的工具 | 绝大多数业务开发发生在这里 |
| 基础设施层 | 保存执行与审计状态，提供观测，连接业务事实 | 配置生产服务、备份、告警和外部系统可靠性 |

## 一次请求怎样穿过系统

以“发布客户报告”为例：

<ol class="gaia-journey gaia-journey--detailed" aria-label="一次请求穿过 Gaia 的过程">
  <li><span>用户</span><strong>创建 Run</strong><small>提交目标与幂等键</small></li>
  <li><span>Gaia API</span><strong>验证入口</strong><small>身份、组织和资源归属</small></li>
  <li><span>Temporal</span><strong>启动持久执行</strong><small>把工作可靠交给 Worker</small></li>
  <li><span>Policy</span><strong>检查写操作</strong><small>发布报告属于高风险动作</small></li>
  <li class="gaia-journey__gate"><span>Human Gate</span><strong>等待可信决定</strong><small>审批人在执行前查看并批准</small></li>
  <li><span>Worker</span><strong>恢复并执行</strong><small>调用客户系统适配器</small></li>
  <li><span>Evidence</span><strong>记录结果</strong><small>状态、决定与工具结果可查询</small></li>
</ol>

这里最重要的不是组件数量，而是两个顺序：

1. 权限和审批发生在副作用之前。
2. 可信决定先由 Gaia 验证和记录，再通知 Temporal 继续。

## 每个组件到底负责什么

| 组件 | 负责 | 不负责 |
| --- | --- | --- |
| 你的业务流程 | 业务步骤和逻辑下一步 | 持久等待、租户鉴权、审计基础设施 |
| 模型 | 理解输入、生成内容、辅助决策 | 最终授权、可靠执行、业务事实真相 |
| 工具适配器 | 连接 CRM、ERP、数据库和内部 API | 决定自己是否有权被调用 |
| Gaia | 身份、Run、策略、Gate、工具准入、审计查询 | 保存客户业务事实、替你制定业务规则 |
| LangGraph | 决定逻辑下一步，并可用 Checkpointer 保存图状态 | 分布式任务所有权、跨服务消息和 Worker 故障接管 |
| In-process Runtime | 单进程执行短流程，把 Run 与事件写入 Gaia 审计投影 | HumanGate、关键副作用、跨进程等待和分布式恢复 |
| Temporal | Workflow History、等待、重试、恢复和执行预算 | 用户权限、业务策略、可信审批授权 |
| Gaia PostgreSQL | 长期审计投影、Run 事件和 Gate 记录 | Temporal 的执行历史、客户主数据 |
| Temporal PostgreSQL | Temporal 自己的持久执行状态 | Gaia 的长期审计查询和业务数据 |
| Langfuse | 模型与工具 trace、token、成本、prompt 观测 | 作为审批或业务事实的权威来源 |
| 客户业务系统 | 订单、客户、库存等权威事实 | Gaia 的运行状态和 Workflow History |

## Gaia 的能力边界

### Gaia 能保证的

- 受支持入口上的身份、组织归属和资源访问控制。
- 工具调用进入适配器前经过准入和策略检查。
- 需要审批的动作在可信决定前不会执行。
- Temporal 模式下，Run 可以持久等待，并按 Runtime 规则恢复或重试。
- 关键状态、Gate 和执行结果形成可查询证据。

### Gaia 不能单独保证的

- 模型输出永远正确。
- 业务适配器没有 bug 或外部系统一定可用。
- 绕过 Gaia 直接调用客户系统的路径仍然安全。
- 组织已经配置了正确的权限、风险和审批责任人。
- “已经发送但响应丢失”的外部副作用可以无条件安全重试。

最后一类问题需要业务工具支持幂等键、查询确认或人工处置，不能靠 Runtime 猜测。

### Runtime Safety 与 Integration Sandbox

Gaia 的安全边界发生在工具 Adapter 执行之前：服务端 `runtime.environment`、环境写入上限、场景
Policy、工具白名单、用户角色、风险等级和 Adapter 注册定义共同决定一次副作用能否进入执行。
客户端请求不能切换服务端环境，模型或 Workflow 也不能自行降低工具风险。

这里的 `sandbox` 是 Integration Sandbox：应用 Profile 必须使用测试系统、最小权限测试凭据、
脱敏或合成数据，以及只允许 sandbox 环境的 Adapter。Gaia 会强制配置与 Adapter 的环境绑定，
但不会凭空创建网络、账号或数据隔离。它不是任意代码执行容器，也不提供 Shell、浏览器或用户
插件的进程级隔离。

## 部署视角

in-process Runtime 只用于开发、测试和 PoC。Gaia 的生产形态默认是 Helm/Kubernetes：横向扩展 API/Worker，
并用 Temporal 承担跨进程等待与恢复：

<div class="gaia-deployment" role="img" aria-label="Gaia 最小生产部署">
  <div><span>入口</span><strong>Gateway</strong><small>统一流量与 TLS</small></div>
  <div><span>无状态接入</span><strong>Gaia API × N</strong><small>独立横向扩展</small></div>
  <div><span>持久编排</span><strong>Temporal Service</strong><small>任务分发与执行历史</small></div>
  <div><span>执行容量</span><strong>Gaia Worker × N</strong><small>按队列独立扩容</small></div>
  <div><span>外部依赖</span><strong>客户系统 + Observability</strong><small>业务事实、Trace 与 Metrics</small></div>
</div>

API 可以横向扩展，Worker 可以独立扩展；Temporal 负责把任务可靠交给 Worker。生产化重点是身份提供方、密钥管理、数据库备份、Worker 发布兼容性、可观测性和故障演练，而不是继续重构 Runtime。

## 接下来读什么

- 想选择本地或生产入口：[选择运行与部署方式](runtime-profiles.md)
- 想构建第一个场景：[开发者指南](developer-guide.md)
- 想从具体场景理解框架：[三个 Case](try-it.md)
- 想理解状态、恢复和审批细节：[运行机制](mechanisms.md)
- 想部署本地生产形态：[生产化本地验证](production-like.md)
- 想调用接口：[HTTP API](http-api.md)
