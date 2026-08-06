# 13 重构施工图：装配打通与 Runtime 拆解

> **历史快照，不代表当前架构。** 本文记录 Temporal 迁移前 Gaia SQL Runtime 的拆解过程，
> 其中 `PersistentRuntimeEngine`、`startup_recover`、Runtime Lease、SQL Run/Gate/Command
> 等描述已被施工图 17 的迁移结果取代。当前边界请以
> [17-TemporalIO-迁移任务清单](17-TemporalIO-迁移任务清单.md)和
> [01-目标架构与模块边界](01-目标架构与模块边界.md)为准。

> 本文是 2026-07-26 第三轮架构评审的落地施工图。目标读者是执行重构的 AI Agent
> （Sonnet 级别即可），每个任务给出准确的文件路径、现有代码锚点、改动步骤、
> 新增测试和验收命令。执行者不需要重新做架构决策，只需要按任务卡施工。

---

## 0. 执行者须知（先读，全程遵守）

### 0.0 施工前置：建立干净基线（任务 A1 之前完成）

**当前工作区是脏的**：`git status --short` 有 93 个条目，其中包含大量
未跟踪的新文件（`src/gaia/api/builder.py`、`src/gaia/runtime/retrieval.py`、
`src/gaia/runtime/tool_execution.py`、迁移 `0010`–`0013`、
多个 `tests/integration/*` 等），本施工图自身也尚未跟踪。

在这个状态下无法执行 §0.1 的"一任务一提交"——每次提交都会把无关的
既有改动裹挟进去，任务边界失效，出问题时无法按任务回退。

**因此 A1 开工前必须先做一次基线提交**，且这次提交**不属于任何任务卡**：

```bash
git status --short          # 先完整浏览，确认没有不该提交的本地实验文件
git add -A
git commit -m "chore: baseline before assembly refactor"
git rev-parse HEAD          # 记下基线 commit，写入本文档施工记录
```

注意事项：

- 提交前逐条看一遍 `git status`，把临时脚本、本地实验、含真实凭据的
  文件排除（必要时补 `.gitignore`），**不要盲目 `git add -A`**；
- 若这些未跟踪文件属于尚未完成的其他工作，与其负责人确认后再提交，
  或先切一个 `refactor/assembly` 分支再建基线；
- 基线建立后运行一次 `make lint && make test` 并记录结果——这是后续
  所有任务"现有测试零断言改动通过"的对照基准。**基线本身如果就有
  失败用例，必须先记录清楚是哪些**，否则无法区分是新引入的问题。

### 0.1 工作方式

1. **一个任务 = 一次独立提交**。任务内列出的文件之外，不要顺手改其他文件。
2. 每个任务完成后必须运行并通过：

   ```bash
   make lint          # ruff check . && mypy src
   make test          # pytest -m "not postgres and not redis and not external"
   ```

3. 涉及 PostgreSQL/Redis 的任务（明确标注）额外运行：

   ```bash
   make test-services
   ```

4. 涉及公共 HTTP 契约的任务（明确标注）额外运行 `make contracts`，
   并提交更新后的 `specs/openapi.json`。
5. 任务卡里的代码草图是**意图说明**，字段名、签名必须照用；实现体允许
   根据现场代码微调，但不允许改变任务卡声明的行为语义。

### 0.1.1 提交闸门：Change Set 四件套（每个任务都会撞上）

本仓库有 Codex Change Set 提交钩子（`scripts/change_set.py` + git hook）。
**直接 `git commit` 会被拒绝**，提示 `No staged verification receipt`。

判定规则在 `scripts/change_set.py` 的 `Impact`（约 200–223 行）：
改动只要落在下列任一目录，就被判为 `public_python`——

```text
src/gaia/api/  contracts/  config/  runtime/  sdk/  starters/
guardrails/  integrations/  model_gateway/  rag/  templates/
```

`public_python` 会同时置起 `tests_required`、`docs_required`、
`release_required` 三个闸门。也就是说**本施工图 A–E 几乎每一个任务**，
提交时都必须同时包含以下四类改动，缺一即被拒：

| 闸门 | 需要的改动 |
| --- | --- |
| tests | 至少一个 `tests/` 下的文件 |
| docs | 至少一个 `developer-docs/` 或 `docs/` 下的文件 |
| release | `CHANGELOG.md` 的 `## Unreleased` 条目 |
| 代码 | 任务本身的实现 |

**这不是官僚流程，是这个框架的工程纪律**：公共行为变了而文档和
CHANGELOG 没变，就是本施工图工程 A 要消灭的那类"文档与实现漂移"。
规划任务时把文档和 CHANGELOG 算进工作量，不要留到最后补。

标准提交流程（每个任务一轮）：

```bash
make change-start INTENT="A1: <任务意图>" KIND=feature   # 或 refactor/docs
# ... 实现 + 测试 + 文档 + CHANGELOG ...
git add -A
make change-ready        # 跑 ruff/mypy/pytest/docs 并写验证回执
git commit -m "..."      # 回执有效才能提交
```

确实无法提供某一类产物时（少见），用位置参数形式登记豁免
（`area` 是位置参数，不是 `--area`）：

```bash
uv run python scripts/change_set.py exempt tests --reason "<至少12字符的真实理由>"
```

`area` 取值 `tests|docs|release`。**理由必须真实**，不要用它绕过纪律。

纯文档任务（只改 `docs/`、`developer-docs/`）不触发这三个闸门，
但仍需要一个 change set manifest 才能提交。

### 0.2 全局禁止事项

- 禁止修改 `src/gaia/runtime/safety.py` 的任何校验逻辑（安全边界冻结）。
- 禁止修改 `src/gaia/contracts/models.py` 中已有字段的类型和语义；
  只允许按任务卡**新增** enum 成员或新模型，并同步更新
  `tests/contract/test_public_models.py`。
- 禁止删除或重命名 `PersistentRuntimeEngine` 的公开方法
  （`create/decide/cancel/transition/inspect/events_after/startup_recover/get_gate/get_command`）。
- 工程 A、B 全程**不改变任何运行时行为**：现有测试除 import 路径外不允许改动断言。
- 新增错误码时必须同步登记 `src/gaia/diagnostics/error_catalog.py`
  （先读该文件了解登记格式）。

### 0.3 关键现状锚点（施工前请逐一打开确认）

| 锚点 | 位置 | 与本施工图的关系 |
| --- | --- | --- |
| `@scenario` 元数据属性 | `src/gaia/sdk/scenario.py` `_SPEC_ATTRIBUTE = "__gaia_scenario_spec__"` | 工程 A 扫描目标 |
| `@read_tool/@write_tool` 元数据属性 | `src/gaia/sdk/tool.py` `_SPEC_ATTRIBUTE = "__gaia_tool_spec__"` | 工程 A 扫描目标 |
| 现成的装配逻辑 | `src/gaia/api/app.py` `ApiDependencies.from_scenarios`（约 76–212 行） | 工程 A 的抽取来源，**不是**新写 |
| 组件注册表 | `src/gaia/components/core.py`（`ComponentKind`、singleton kind 列表在 `_register` 内） | 工程 A 需新增 kind |
| Starter 契约 | `src/gaia/starters/core.py`（`GaiaStarter` Protocol、条件类型） | 工程 A 新增 starter |
| 内置 Starter | `src/gaia/starters/builtin.py`（约 507 行，含 `BUILTIN_STARTERS`、`STARTER_DEPENDENCIES`） | 工程 A 注册点 |
| 引擎上帝类 | `src/gaia/runtime/persistent_engine.py`（1980 行） | 工程 B 拆解对象 |
| 已有 Ledger | `src/gaia/runtime/ledger.py`（`RuntimeLedger`，按 session 构造） | 工程 B 低层落点 |
| 状态机文档 | `docs/施工图/02-Runtime状态机与事务边界.md` | 工程 B 的事实来源之一 |
| 配置模型 | `src/gaia/config/models.py`（`StrictModel`、`GaiaApplicationConfig` 在 239 行附近） | 工程 A/C 扩展点 |
| 迁移版本 | `src/gaia/persistence/migrations/versions/`（当前最新 `0013_runtime_continuation.py`） | 工程 D 新增 `0014` |
| 项目生成模板 | `src/gaia/templates/project.py` | 工程 A 的 DX 收尾 |

---

## 1. 背景与目标状态

第三轮评审结论（按优先级）：

1. **P0 装配断裂**：`GaiaApplication`/Starter/AutoConfigurator 产出的组件图只供
   Actuator 和 Dev Console 展示；真正的执行引擎由业务方手写 composition root
   （或调用 `ApiDependencies.from_scenarios`）组装。`gaia.yaml` 声明的东西和
   实际运行的东西是两份事实。
2. **P1 上帝类**：`PersistentRuntimeEngine` 单类承担 Run 生命周期、Gate、
   Command、Action Plan、Handoff、Continuation、恢复、预算、快照，状态机隐式。
3. **P1 治理硬编码**：`@scenario` 中 `rules_version` 等版本号是手填字符串，
   会与内容漂移；策略收紧必须走代码发布。
4. **P2 单实例假设未声明**：`startup_recover` 无互斥，双副本部署会双重恢复。
5. **P3 清理项**：`get_component` 返回 `Any` 且错误码不走 catalog、
   `framework_version` 硬编码、认证只有 api_key。

目标状态：

- 业务应用只需要 `gaia.yaml`（声明 `scenarios.modules`）+ 装饰器函数文件，
  `create_app(gaia_application=...)` 即可获得完整受控 Runtime；
- Actuator 组件图中出现 `runtime-assembler` 组件，展示与运行同源；
- 引擎状态迁移有单一权威表，非法迁移在测试期即失败；
- 版本号可由内容指纹生成，策略可由配置**只收紧**地覆盖；
- 恢复有数据库租约，部署拓扑边界写入文档。

---

## 2. 工程总览与执行顺序

| 工程 | 内容 | 优先级 | 前置 | 任务数 |
| --- | --- | --- | --- | --- |
| A | 声明式装配打通（decorator → Starter → Runtime） | P0 | 无 | A1–A7（含 A4b） |
| B | 状态机显式化 + 引擎拆解 | P1 | 无（可与 A 并行，但建议 A 后做） | B1–B6 |
| C | 版本指纹 + 策略收紧覆盖 | P1 | C2 依赖 **A3 + C1** | C1–C2 |
| D | 恢复租约 + 部署边界声明 | P2 | 无 | D1–D2 |
| E | 清理项 | P3 | 无 | E1–E3 |
| F | 评审整改（阻断项） | **P0** | 无 | F1–F6 |
| G | 死代码清理与定位调整 | P2 | 无 | G1–G2 |
| H | 可用性缺口（实机发现） | **P0** | 无 | H0–H3 |

**推荐执行顺序**：A1→A2→A3→A4→A4b→A5→A6→A7 → B1→B2→B3→B4→B5→B6 → C1→C2 → D1→D2 → E1→E2→E3 → **F1→F2→F3→F4→F5→F6** → G1→G2 → **H0→H1→H2→H3**。

工程 A 的 7 个任务**全部必做**。A6（handoff/continuation 声明式发现）
曾被标为可选，现已改为必做：缺了它，多 Agent 与写后续接类应用仍需手工
Builder，双装配问题只是被缩小范围而非解决。

里程碑验收：M1 = **A4 + A4b** 完成（声明式路径端到端跑通，只读与模型两类场景
均无需手工装配；A4 单独完成只覆盖只读场景）；M2 = A7（含 A6）；
M3 = B1；M4 = B5；M5 = C2；M6 = D2。每个里程碑处运行完整验收（§8）。

---

## 3. 工程 A：声明式装配打通（P0）

设计总述：`from_scenarios` 内已经存在完整的"从 ScenarioSpec/工具函数组装
`PersistentRuntimeEngine`"的逻辑（guardrail 管道、预算、观测包装、
PromptRunVersionResolver 全都有）。工程 A 做四件事：

1. 把这段逻辑**抽取**为独立的 `RuntimeAssembler`（无行为变化）；
2. 新增**模块扫描**（从 `gaia.yaml` 的 `scenarios.modules` 发现装饰器函数）；
3. 新增 **`scenario-runtime` Starter**，把 `RuntimeAssembler` 注册为组件；
4. 让 `create_app` 在未显式传 `dependencies` 时从组件图取 assembler。

### A1 配置模型：`scenarios` 段

**改动文件**：`src/gaia/config/models.py`、`tests/unit/`（找到现有配置模型
测试文件，通常是 `test_config*.py`，在其中加用例）。

**步骤**：

1. 在 `config/models.py` 中新增（放在 `RagSettings` 之后、
   `GaiaApplicationConfig` 之前）：

   ```python
   class ScenarioSettings(StrictModel):
       """Declarative discovery of @scenario / @read_tool / @write_tool modules."""

       modules: tuple[str, ...] = ()
   ```

2. 在 `GaiaApplicationConfig` 中新增字段 `scenarios: ScenarioSettings`，
   默认 `ScenarioSettings()`。模仿相邻字段（如 `prompt`、`rag`）的写法，
   包括默认值工厂和 `redacted()`/`stable_hash()` 是否需要处理
   （先阅读这两个方法，`modules` 是纯字符串元组，不含 secret，
   通常无需特殊处理，但必须确认 hash 覆盖到新字段）。

**新增测试**：配置解析用例——yaml 中写

```yaml
gaia:
  scenarios:
    modules: [myapp.flows, myapp.tools]
```

断言 `config.scenarios.modules == ("myapp.flows", "myapp.tools")`；
以及未声明时默认为空元组。

**验收**：`make lint && make test`。

### A2 模块扫描器 `scenario_discovery`

**新增文件**：`src/gaia/starters/scenario_discovery.py`、
`tests/unit/test_scenario_discovery.py`。

**步骤**：

1. 实现：

   ```python
   """Import-time discovery of decorated scenarios and tools."""

   from __future__ import annotations

   import importlib
   from dataclasses import dataclass

   from gaia.sdk.scenario import ScenarioSpec
   from gaia.sdk.tool import FunctionToolSpec, ToolHandler
   from gaia.sdk.scenario import ScenarioHandler

   _SCENARIO_ATTR = "__gaia_scenario_spec__"
   _TOOL_ATTR = "__gaia_tool_spec__"


   @dataclass(frozen=True)
   class DiscoveredScenarios:
       scenarios: tuple[ScenarioSpec, ...]
       scenario_handlers: tuple[ScenarioHandler, ...]
       tool_handlers: tuple[ToolHandler, ...]


   class ScenarioDiscoveryError(ValueError):
       def __init__(self, code: str, detail: str) -> None:
           super().__init__(f"{code}:{detail}")
           self.code = code
           self.detail = detail


   def discover_scenarios(modules: tuple[str, ...]) -> DiscoveredScenarios: ...
   ```

2. `discover_scenarios` 逻辑：
   - 逐个 `importlib.import_module(name)`；`ModuleNotFoundError` 时抛
     `ScenarioDiscoveryError("SCENARIO_MODULE_NOT_FOUND", name)`；
   - 遍历 `vars(module).items()`，只看**该模块自己定义**的成员
     （`getattr(obj, "__module__", None) == module.__name__`，避免把
     import 进来的别人的场景重复注册）；
   - `hasattr(obj, _SCENARIO_ATTR)` → 收集 handler 与
     `get_scenario_spec(obj)`；`hasattr(obj, _TOOL_ATTR)` → 收集 handler；
   - 结果按 `scenario_id` / 工具名排序，保证确定性；
   - `scenario_id` 重复时抛
     `ScenarioDiscoveryError("SCENARIO_DUPLICATE", scenario_id)`；
     工具名重复同理（`SCENARIO_TOOL_DUPLICATE`）。

3. 两个错误码登记到 `src/gaia/diagnostics/error_catalog.py`
   （先读该文件，按现有条目格式补：含错误说明与操作建议）。

#### A2.1 Scenario 模块纯净性契约（必做）

`importlib.import_module` 会执行模块顶层代码。如果业务方在 Scenario 模块
顶层连数据库、读 Secret、创建 HTTP Client，那么"装配"就变成了"副作用发生
在框架控制之外"——`GaiaApplication` 的零副作用装配计划、
`AsyncExitStack` 资源作用域和失败回滚全部失效，`gaia check` 这类只做
静态检查的命令也会意外触发真实连接。这条契约是工程 A 的安全前提。

**契约（写入 docstring 与 `developer-docs/`）**：Scenario 模块只允许在
导入期做以下事情——定义函数与类、定义常量、贴装饰器元数据、import 其他
纯模块。禁止在导入期：建立网络/数据库连接、解析 Secret、读写文件、
创建需要释放的 Client、启动线程或事件循环。所有资源必须通过 Starter
注册为 `ComponentScope.APPLICATION` 组件，由 lifespan 管理。

**实现方式：静态检查，不做运行时 monkeypatch。**

> 施工须知：本节的早期草案曾要求在 discovery 的 import 窗口内 patch
> `socket.socket.connect` 与 `resolve_secret`。该方案已被**否决**，
> 不要实现。否决理由：(a) `socket.socket.connect` 是 C 层类型方法，
> monkeypatch 不保证稳定；(b) patch 是进程全局的，启动期其他线程和
> 组件会被误伤；(c) 目标模块若已 `from gaia.config.secrets import
> resolve_secret`，patch 原模块属性对它无效；(d) 它只能拦住少数 I/O
> 形式，却会让使用者误以为得到了真正的隔离——这比不做更危险。
> **任何情况下都不要在应用启动进程里做全局 patch。**

分两层落地：

**第一层（主约束）：框架契约。** 就是上面那段契约文本，写入
`scenario_discovery.py` 模块 docstring、`@scenario` 的文档、
`developer-docs/` 的场景编写章节。违约的后果（资源逃出 lifespan
管理、`gaia check` 触发真实连接）要写清楚，让人知道为什么。

**第二层（辅助检查）：`gaia check` 的 AST 静态检查。**
新增 `src/gaia/diagnostics/import_purity.py`：

```python
@dataclass(frozen=True)
class PurityFinding:
    module: str
    line: int
    symbol: str      # 触发的调用名，如 "resolve_secret"
    hint: str        # 操作建议


def scan_module_purity(module_name: str) -> tuple[PurityFinding, ...]:
    """Flag obvious import-time I/O without importing the module."""
```

要点：

- **不 import 目标模块**。用 `importlib.util.find_spec(module_name)`
  拿 `spec.origin` 路径，读源码，`ast.parse` 后只遍历**模块顶层语句**
  （`ast.Module.body`，以及顶层 `if`/`try` 的分支体；函数体和类体内的
  调用一律忽略——那些是运行期，不是导入期）；
  注意 `find_spec` 会导入父包，这一点在 docstring 里注明；
- **命中规则必须按"来源"匹配，不能按裸调用名匹配**。
  按名字匹配 `connect` / `Client` / `from_url` 会误报业务方自己的
  `Client()` 或任意对象的 `.connect()`，与"宁可漏报不误报"直接矛盾；
  `gaia check` 一旦开始挡正常项目，使用者就会绕开它，这个检查也就废了。

  做法：先扫模块顶层的 `import` / `from ... import` 建立
  **alias 表**（`{本地名: 完全限定名}`），再对顶层调用求解其完全限定名，
  只有落在下面这张白名单里才算命中：

  ```python
  IMPURE_CALLS: frozenset[str] = frozenset({
      "gaia.config.secrets.resolve_secret",
      "sqlalchemy.create_engine",
      "sqlalchemy.ext.asyncio.create_async_engine",
      "httpx.Client",
      "httpx.AsyncClient",
      "redis.Redis.from_url",
      "redis.asyncio.Redis.from_url",
      "builtins.open",
  })
  ```

  两种 import 形式都要解析：`import httpx` → `httpx.Client(...)`；
  `from httpx import Client` → `Client(...)`；`as` 别名同样处理。
  **解析不出来源的调用一律不报**（裸 `Client()`、`obj.connect()`、
  动态 import 的结果）——这是刻意的漏报，不是缺陷；
- 规则表用模块级常量声明，方便后续增补，并在 docstring 注明
  "增补时只加完全限定名，永远不要加裸名字"；
- 输出是 **findings，不是异常**：`scan_module_purity` 只返回结果，
  由调用方决定严厉程度。
- `cli/main.py` 的 `_check`（约 239 行）**在 `configure()` 之前**先跑
  这个扫描——顺序很重要，因为 A4 之后 `configure()` 会通过
  `scenario-runtime` starter 触发真实 import，扫描放在后面就没意义了。
  findings 写入 `_check` 返回 payload 的 `"issues"` 字段，
  并让 `ok=False`、退出码 2。
- `discover_scenarios` 本身**不做**这个检查（保持 discovery 纯粹、
  无额外 I/O，且避免每次启动都读源码解析 AST）。

**未来演进（本次不实现，仅登记方向）**：若确实需要动态探测，正确做法是
在**独立子进程**中 import 目标模块并观察其行为，主进程只读结果。
把这句写进 `import_purity.py` 的模块 docstring，避免后人再走回
monkeypatch 的老路。

**诚实表述要求**：文档中不得把这层检查描述为隔离或安全边界。它是
best-effort 的 lint，口吻对齐 `09-Runtime安全边界与Sandbox.md` 对
Sandbox 边界的表述。

**新增测试**：
- `tests/unit/test_scenario_discovery.py`：用 `types.ModuleType` +
  `sys.modules` 注入假模块（模仿仓库现有写法），覆盖正常发现并排序、
  模块不存在、scenario_id 重复、跨模块 import 不重复收集；
- `tests/unit/test_import_purity.py`：用 `tmp_path` 写真实 `.py` 文件
  并加入 `sys.path`，覆盖——
  - 顶层 `resolve_secret()` 被命中并给出行号；
  - `import httpx` + 顶层 `httpx.Client()` 被命中；
  - `from httpx import AsyncClient as C` + 顶层 `C()` 被命中（别名解析）；
  - **函数体内**的同名调用**不**被命中（这条必须有）；
  - **业务方自定义的 `Client()`**（本地定义的类，非 httpx）
    **不**被命中（防误报，这条必须有）；
  - 任意对象的 `obj.connect()` **不**被命中；
  - 纯净模块返回空 findings；
- CLI 用例：`gaia check` 对含违约模块的配置返回退出码 2 且 issues 非空。

**验收**：`make lint && make test`。

### A3 抽取 `RuntimeAssembler`（无行为变化）

**改动文件**：新增 `src/gaia/runtime/assembly.py`；
修改 `src/gaia/api/app.py`（`ApiDependencies.from_scenarios` 变薄）。

**步骤**：

1. 新建 `src/gaia/runtime/assembly.py`，定义：

   ```python
   @dataclass(frozen=True)
   class RuntimeAssembler:
       """Builds the durable runtime engine from declarative scenario specs.

       This is the single assembly path shared by ApiDependencies.from_scenarios
       and the scenario-runtime starter."""

       config: GaiaApplicationConfig
       scenario_handlers: tuple[ScenarioHandler, ...]
       tool_handlers: tuple[ToolHandler, ...]
       model_provider: ModelProvider | None = None
       retriever: Retriever | Callable[[], Retriever] | None = None
       guardrails: Mapping[GuardrailStage, tuple[ContentGuardrail, ...]] | None = None
       prompt_provider: PromptProvider | Callable[[], PromptProvider] | None = None
       handoff_handlers: Mapping[str, ScenarioHandler] | None = None
       continuation_handlers: Mapping[str, ScenarioHandler] | None = None
       allowed_handoffs: Mapping[str, tuple[str, ...]] | None = None
       max_handoffs: int = 4
       output_correction_attempts: int = 0

       def create_engine(
           self,
           session_factory: async_sessionmaker[AsyncSession],
           database_url: str,
       ) -> PersistentRuntimeEngine: ...
   ```

2. `create_engine` 的实现 = 现在 `from_scenarios` 内嵌 `runtime_factory`
   函数体的**原样搬移**（`api/app.py` 约 121–210 行）：spec 校验、
   `ToolRegistry(function_tool(...))`、`SqlAlchemyRunBudgetStore`、
   guardrail 管道、`InstrumentedModelProvider` → `BudgetedModelProvider` →
   `GuardedModelProvider` 包装链、`PromptRunVersionResolver`、
   `FunctionScenarioRunner` 构造、`RuntimeDependencies` 构造。
   spec 去重校验（duplicate scenario_id / duplicate tool handler）
   搬到 `__post_init__`。
3. `ApiDependencies.from_scenarios` 改为：构造 `RuntimeAssembler`，
   `runtime_factory = assembler.create_engine`，其余参数归一化
   （`_normalize_guardrails`）逻辑保留在 api 层或一并下移——
   **选择一并下移**到 `assembly.py`（api 层只剩转发），
   `_normalize_guardrails` 移动后在 `api/app.py` 内保留
   `from gaia.runtime.assembly import _normalize_guardrails` 的引用或直接删除原定义。
4. 注意 import 方向：`assembly.py` 属于 runtime 层，**不得 import
   `gaia.api` 下任何东西**（用 `make lint` 的 mypy 加人工检查确认）。

5. **唯一实现位置（硬约束）**：`RuntimeAssembler.create_engine` 是
   全仓库唯一一处"把 spec/工具组装成 `PersistentRuntimeEngine`"的代码。
   `ApiDependencies.from_scenarios` 与 A4 的 `scenario-runtime` Starter
   都只能**委托**它，不允许各自保留一份相似的组装逻辑——否则双装配
   问题只是从"业务侧 vs 框架侧"变成了"框架内两处"，工程 A 的意义丧失。
   自检命令（应只在 `assembly.py` 内命中构造调用）：

   ```bash
   grep -rn "PersistentRuntimeEngine(" src/ examples/ | grep -v "assembly.py"
   ```

   除测试外若有其他命中，说明抽取不彻底，必须继续收敛。
   `examples/controlled_task` 的 `composition.create_runtime` 是自定义
   `ScenarioRunner` SPI 路径（非装饰器路径），属于**已知例外**，
   保留并在此处注明理由即可。

**测试**：不新增；本任务的验收就是**现有全部测试不改一行断言通过**
（`tests/contract/test_starters.py`、api 相关 contract 测试覆盖了
`from_scenarios` 路径）。

**验收**：`make lint && make test`，外加上面的 grep 自检。

### A4 `scenario-runtime` Starter + `create_app` 接线

**改动文件**：`src/gaia/components/core.py`、`src/gaia/starters/builtin.py`、
`src/gaia/api/app.py`、`tests/contract/test_starters.py`（新增用例）。

**步骤**：

1. `components/core.py`：`ComponentKind` 新增成员 `RUNTIME = "runtime"`；
   在 `_register` 的 singleton kind 集合（约 110–125 行）中加入
   `ComponentKind.RUNTIME`（一个应用只能有一个 runtime assembler）。
2. `starters/builtin.py`：新增 starter（模仿现有 starter 类的写法，
   先读该文件确认 `GaiaStarter` 实现惯例）：

   - `starter_id = "scenario-runtime"`，capabilities `("runtime-assembly",)`；
   - `defaults()` 返回 `{}`；
   - `conditions()`：返回一个自定义条件 `OnScenarioModules`
     （在 `starters/core.py` 新增该条件类型，`match` 逻辑：
     `bool(config.scenarios.modules)`，reason 形如
     `f"scenarios.modules={list(config.scenarios.modules)}"`)；
   - `contribute(registry, config)`：
     a. `discovered = discover_scenarios(config.scenarios.modules)`；
     b. 收集 registry 中已注册的 MODEL / PROMPT / RAG kind 组件 id，
        作为 `depends_on`；
     c. 注册 STATIC 组件：

        ```python
        ComponentDescriptor(
            component_id="runtime-assembler",
            kind=ComponentKind.RUNTIME,
            implementation="gaia.runtime.assembly.RuntimeAssembler",
            starter_id="scenario-runtime",
            profile=config.profile,
            depends_on=tuple(依赖的组件 id),
            configuration_keys=("scenarios.modules", "runtime.environment"),
            reason="scenarios.modules is configured",
        )
        ```

        factory 从 resolver（`ComponentResolver` 即已实例化组件的 mapping）
        中按 id 取出 model provider / prompt provider / retriever 实例
        （不存在则传 `None`），构造 `RuntimeAssembler`。
     d. **侦察结论（2026-07-26 已完成，假设被证伪，勿再假设）**：
        `model-mock`、`model-openai-compatible`、`workflow-langgraph`、
        `context-mock`、`policy-controlled` 等都由 `builtin.py` 的
        `_starter()` 工厂生成 `BuiltinStarter`，其 `contribute()` 注册的
        factory 是：

        ```python
        lambda _components: {"starter": self.descriptor.starter_id}
        ```

        **返回的是标记字典，不是 `ModelProvider` 实现。** 这类组件当前
        纯粹服务于 Actuator 与 Dev Console 的展示。仓库里真正注册实例的
        starter 用的是另一条路径（`RedisClientStarter` 等的
        `register_resource`）。

        这比本施工图 §1 对 P0 的描述更严重：不只是"Runtime 不消费组件图"，
        而是**组件图的核心节点里没有可被消费的东西**。因此 A4 不能从
        resolver 取 model provider——那只会拿到一个字典。

        A4 的做法：从 resolver 取到对象后做 `isinstance(obj, ModelProvider)`
        判定，**只有真实 provider 才注入**，占位字典一律视为不存在
        （`model_provider=None`）。据此 A4 交付的是只读场景的端到端闭环。
        让模型类场景也走通，由新增任务 **A4b** 负责。
   - 将 starter 加入 `BUILTIN_STARTERS`；`STARTER_DEPENDENCIES` 无需新增。
3. `api/app.py` `create_app`：在 lifespan 内（当前约 290–300 行，
   `managed_application.lifespan()` 已进入之后）修改 runtime 构造逻辑：

   ```python
   runtime_engine = None
   if dependencies is not None:
       runtime_engine = dependencies.runtime_factory(factory, configured_database)
   else:
       assembler = _optional_component(managed_application, "runtime-assembler")
       if assembler is not None:
           runtime_engine = assembler.create_engine(factory, configured_database)
   ```

   `_optional_component`：捕获 `KeyError`/未启动错误并返回 `None` 的小工具函数。
   显式传入的 `dependencies` **永远优先**（保持现有应用行为不变）。

**新增测试**（加入 `tests/contract/test_starters.py` 或新建
`tests/contract/test_scenario_runtime_starter.py`）：

1. 构造临时模块（含一个 `@scenario` 只读场景 + 一个 `@read_tool`），
   写一份最小 `gaia.yaml`（starters 含 `core-runtime`、`model-mock`、
   `scenario-runtime`，`scenarios.modules` 指向临时模块）；
2. `GaiaApplication.from_config` → `configure()`，断言
   `actuator_snapshot().components` 中存在 `runtime-assembler`；
3. 用 `create_app(gaia_application=...)`（不传 `dependencies`）+
   `httpx.AsyncClient`/`TestClient`（模仿现有 api contract 测试的客户端写法）
   发起一次只读 Run，断言 `succeeded`；
4. 反向用例：`scenarios.modules` 为空时 starter 条件不匹配，
   `AutoConfigurationReport.negative` 中出现 `scenario-runtime`。

**验收**：`make lint && make test`。A4 交付只读场景的端到端闭环；
**M1 里程碑要等 A4b 完成**（见下）。

### A4b 让核心 Starter 注册真实实例（由 A4 侦察结论催生）

**背景**：A4 的侦察证实 `model-mock` / `model-openai-compatible` 注册的是
标记字典而非 `ModelProvider`。只要这一点不变，声明式路径就只能跑只读场景，
凡是调模型的场景仍需应用方手工传 `model_provider`——双装配问题在最常见的
场景类型上原样存在。**因此 A4b 不是可选优化，是 M1 成立的必要条件。**

**改动文件**：`src/gaia/starters/builtin.py`、
`src/gaia/model_gateway/`（可能需新增 mock provider）、
`tests/contract/test_model_providers.py`（已存在，先读）。

**步骤**：

1. **先读 `tests/contract/test_model_providers.py`**，确认框架对
   `ModelProvider` 契约的既有断言，新实现必须满足同一套契约。
2. `model-openai-compatible` 的 `contribute()` 改为注册真实实例：
   用 `gaia.model_gateway.openai_compatible.OpenAICompatibleProvider`，
   参数从 `config.model` 取（`base_url`、`model_id`、`api_key` 走
   `SecretRef` 解析，**Actuator 只保留引用不保留明文**，对齐既有做法）。
   provider 若持有需要释放的 client，用 `register_resource` +
   `ComponentScope.APPLICATION`，不要用 `register`。
3. `model-mock` 需要一个框架内的确定性 mock provider。
   `examples/controlled_task/model.py` 有 `DeterministicMockProvider`，
   但它在 examples 里，**框架不能依赖 examples**。做法：在
   `src/gaia/model_gateway/` 下新增一个等价的确定性 mock（可参考
   examples 版本的行为），examples 保持不动。
4. 保留"应用显式提供的同 kind 组件即视为替换"的现有语义
   （`BuiltinStarter.contribute` 开头那段 `if any(item.kind == self.kind...)`
   要在新实现里保持等价行为）。
5. A4 中的端口判定保持不变——它此时会真正命中，无需改动 assembler。
6. **新增 `ModelEndpointProfile` 构造助手**（侦察发现框架缺这一环）：
   `config.model` 已有 `provider`/`model_id`/`base_url`/`api_key`/
   `timeout_seconds`，但没有任何函数把它们变成调用模型所需的
   `ModelEndpointProfile`（该类型定义在 `contracts/models.py:471`，
   还需要 `protocol` 与 `capabilities`）。没有它，每个声明式场景都要手写
   一遍 profile，A5 的"app.py ≤15 行"和场景的简洁性都无从谈起。
   在 `src/gaia/model_gateway/` 新增：

   ```python
   def model_endpoint_profile_from_config(config: GaiaApplicationConfig) -> ModelEndpointProfile:
   ```

   `api_key` 走 `SecretRef` 解析；**解析后的值不得进入 Actuator 快照**。

**验收**：
- `make lint && make test`；
- **契约测试**（不是 examples——`examples/function_task` 要到 A5 才创建）：
  构造一份含 `model-mock` + `scenario-runtime` 的配置，让一个声明式场景
  通过 `ctx.model` 完成一次结构化生成，端到端断言 `succeeded`；
- Actuator 快照里 MODEL 组件的 `implementation` 字段是真实类名，
  不再是 `gaia.starters.model-mock`。

此为 **里程碑 M1**：到此为止，`gaia.yaml` 里声明的东西才第一次等于
Runtime 实际使用的东西，只读与模型两类场景都不需要手工装配。

### A5 声明式参考应用 `examples/function_task`

**新增目录**：`examples/function_task/`。**不改动** `examples/controlled_task`
（它的价值是验证自定义 `ScenarioRunner` SPI，保留）。

**步骤**：

1. 内容（刻意保持最小，这个目录就是 DX 的度量尺）：
   - `flows.py`：一个 `@scenario` 只读场景 + 一个带
     `ScenarioResponse.propose` 写路径的场景；
   - `tools.py`：一个 `@read_tool` + 一个 `@write_tool`（带 mock 环境
     `allowed_environments`，写一个内存字典的 `WriteAdapter`）；
   - `gaia.yaml`：starters = `core-runtime`、`model-mock`、
     `scenario-runtime`；`scenarios.modules` 指向上面两个模块；
   - `app.py`：目标是**只有这几行**——

     ```python
     from pathlib import Path
     from gaia.api.app import create_app
     from gaia.application import GaiaApplication

     def build() -> FastAPI:
         return create_app(
             gaia_application=GaiaApplication.from_config(Path(__file__).parent / "gaia.yaml")
         )
     ```

     如果写不到这么短，说明 A4 有缺口，先回去补 A4，不要在 app.py 里加胶水。
2. 写场景经 HumanGate 审批后执行的端到端集成测试
   （`tests/integration/test_function_task_example.py`，模仿现有
   controlled_task 集成测试的结构：create run → 查 gate → decide →
   断言 command 执行与终态）。

**验收**：`make lint && make test`。

### A6 handoff / continuation 的声明式发现（必做，不可跳过）

**为什么不能跳过**：只要 handoff 与 continuation 无法被声明式发现，
任何使用多 Agent 或写后续接的应用就必须回到手工构造
`RuntimeAssembler`/`ApiDependencies` 的老路。那样双装配问题只是从
"所有应用"缩小到"高级应用"，并没有被解决——而高级应用恰恰是最需要
受控执行和组件图可解释性的那一类。**A6 未完成时，工程 A 不算完成，
不得进入里程碑 M2。**

前置：A5 完成且稳定。

**改动文件**：`src/gaia/sdk/scenario.py`、
`src/gaia/starters/scenario_discovery.py`、`src/gaia/runtime/assembly.py`。

**步骤**：

1. `sdk/scenario.py` 新增两个装饰器（模式与 `@scenario` 相同，只贴元数据）：

   ```python
   @agent_handler("triage", allowed_handoffs=("specialist",))
   # 属性名 __gaia_agent_handler__，值为 frozen dataclass:
   #   AgentHandlerSpec(agent_id: str, allowed_handoffs: tuple[str, ...])

   @continuation_handler("after-write")
   # 属性名 __gaia_continuation_handler__，值为 str
   ```

   `@scenario` 新增参数 `allowed_handoffs: tuple[str, ...] = ()`，
   存入 `ScenarioSpec`（新增字段，注意同步 `tests/contract/test_public_models.py`
   如有覆盖）。

   **为什么 `@agent_handler` 必须自带 `allowed_handoffs`**：Runtime 的
   `allowed_handoffs` 是一张**逐跳路由表**，key 既包含 `"scenario"`
   也包含每个 agent 名：

   ```python
   {"scenario": ("triage",), "triage": ("specialist",)}
   ```

   `scenario(allowed_handoffs=...)` 只能描述 Scenario 这一个出口。
   `triage → specialist` 这一跳如果没有声明来源，装配期就只能靠猜
   （要么全连通、要么全禁止），两者都不可接受——全连通等于放弃
   `HANDOFF_NOT_ALLOWED` 这道校验。因此每个 agent 自己声明自己的出口，
   路由表由各声明拼装，**不设任何隐式默认边**：未声明即不可达。

2. `discover_scenarios` 同时收集两类 handler，`DiscoveredScenarios`
   增加字段：`agent_handlers: Mapping[str, ScenarioHandler]`、
   `agent_routes: Mapping[str, tuple[str, ...]]`、
   `continuation_handlers: Mapping[str, ScenarioHandler]`。

   **发现期校验与错误码**（都在装配期 fail fast，不留到运行时）：

   | 情况 | 错误码 | 是否新增 |
   | --- | --- | --- |
   | 同一 `agent_id` 被两个函数声明 | `AGENT_HANDLER_DUPLICATE` | **新增** |
   | 同一 continuation 名被两个函数声明 | `CONTINUATION_HANDLER_DUPLICATE` | **新增** |
   | 某条路由的目标 agent 未被任何 `@agent_handler` 声明 | `HANDOFF_TARGET_NOT_FOUND` | 已存在，复用 |

   `HANDOFF_TARGET_NOT_FOUND`、`HANDOFF_NOT_ALLOWED`、
   `CONTINUATION_HANDLER_NOT_FOUND` 已在
   `contracts/models.py` `ErrorCode`（约 137–139 行）定义，
   **直接复用，不要重复定义**。只新增上表标注的两个 duplicate 码，
   并同步 `error_catalog.py` 与 `tests/contract/test_public_models.py`。
3. `RuntimeAssembler` 用发现结果填充 `handoff_handlers` /
   `continuation_handlers` / `allowed_handoffs`。路由表拼装方式：

   ```python
   allowed_handoffs = {
       "scenario": spec.allowed_handoffs,      # 来自 @scenario
       **discovered.agent_routes,              # 来自各 @agent_handler
   }
   ```

   多场景应用中每个 `FunctionScenarioRunner` 用自己 spec 的
   `allowed_handoffs` 作为 `"scenario"` 键，agent 之间的路由表共享。
   注意 `FunctionScenarioRunner.__init__` 已有的三条校验
   （未知 handoff 源、未知 handoff 目标、`max_handoffs >= 0`）会在装配期
   触发，这是期望行为：声明错误必须在应用启动时暴露，不能留到运行时。
4. `examples/function_task` 扩充：新增一个 `@agent_handler` 目标与一个
   `@continuation_handler`，让参考应用覆盖 handoff 与写后续接两条路径，
   且 `app.py` 保持 ≤15 行不变。**这是 A6 是否真正完成的判据**——
   如果为了接上 handoff 又往 app.py 加了胶水，说明 discovery 或
   assembler 有缺口，回去补，不要在应用侧妥协。
5. 测试：discovery 单测（发现 agent/continuation handler、
   `allowed_handoffs` 解析、非法声明在装配期报错）+ 一个经 handoff
   的端到端用例 + 一个写审批通过后走 continuation 的端到端用例。

**验收**：`make lint && make test`。

### A7 `gaia init` 模板与文档收口

**改动文件**：`src/gaia/templates/project.py`、`README.md`、
`developer-docs/developer-guide.md`、`developer-docs/getting-started.md`、
`docs/施工图/01-目标架构与模块边界.md`、`docs/施工图/实现状态.md`。

**步骤**：

1. 打开 `templates/project.py`，找到生成 `app.py`/`gaia.yaml` 的模板段：
   生成的项目改为 A5 的形态（`scenarios.modules` + 极简 `app.py`），
   删除模板中生成手工 composition 的部分（先确认现有模板生成什么，
   对照修改；模板相关测试在 `tests/` 里搜 `templates` 或 `init`）。
2. 文档：README「当前实现」加一条声明式装配；developer-guide 用
   function_task 作为首选起步路径；`01-目标架构与模块边界.md` 的结构图中
   把 Execution Runtime 标注为"由 scenario-runtime Starter 自动装配"。
3. `docs/施工图/实现状态.md` 登记工程 A 完成状态。

**验收**：`make lint && make test`，`uv run gaia init /tmp/gaia-a7-check`
生成的项目能通过 `uv run gaia check`（在生成目录内执行，具体命令先看
`gaia init` 现有输出提示）。此为 **里程碑 M2**。

---

## 4. 工程 B：状态机显式化与引擎拆解（P1）

原则：**只搬家、不改行为**。每个任务结束时现有测试零断言改动通过。
拆解后 `PersistentRuntimeEngine` 保留为对外 façade，公开方法签名不变。

### B1 显式状态迁移表

> **侦察结论（2026-07-27 已完成，本卡据此改写）**：框架里**已经存在**
> `src/gaia/runtime/lifecycle.py`，内含 `ALLOWED_TRANSITIONS`（RunStatus 迁移表）
> 与 `validate_transition()`，语义与本卡原先设想的一致。
> 因此**不要新建 `state_machine.py`**——那会造出第二张迁移表，正是本施工图
> 一路在消灭的"两份事实"。B1 改为**扩充 `lifecycle.py`**。
>
> 实测缺口：
> - `persistent_engine.py` 有 16 处 RunStatus 写入，只有 5 处走
>   `validate_transition`，其余 11 处是裸 `run.status = ...`，**绕过校验**；
> - `GateStatus`、`CommandStatus`、`ActionStatus` **没有任何迁移表**；
> - 裸赋值中存在 `RUNNING -> RUNNING` 自环（约 1591/1831/1833 行），
>   而现有表**不允许**该迁移——这正是它们被写成裸赋值的原因。
>   处理原则见下方第 3 步：补表并注释场景，不得放宽成全通过。

**改动文件**：`src/gaia/runtime/lifecycle.py`（扩充，不新建）、
`tests/unit/test_lifecycle.py`（若不存在则新建）。
**修改**：`src/gaia/runtime/persistent_engine.py`（`_transition`、
`_set_run_error`、`decide` 中 gate 状态变更、command 状态变更处）、
`src/gaia/contracts/models.py`（`ErrorCode` 新增 `RUNTIME_ILLEGAL_TRANSITION`）。

**步骤**：

1. **侦察（必做，先于写码）**：
   - 通读 `docs/施工图/02-Runtime状态机与事务边界.md`；
   - `grep -n "_transition(\|status=RunStatus\.\|GateStatus\.\|CommandStatus\.\|ActionStatus\." src/gaia/runtime/persistent_engine.py`
     列出全部状态写入点，整理成"当前实际发生的迁移"清单；
   - 文档与代码冲突时**以代码为准**，并把冲突记录在提交说明里。
2. 实现迁移表（以下是基于 `RunStatus` 定义的初始假设，必须用步骤 1
   的侦察结果修正后再落码）：

   ```python
   RUN_TRANSITIONS: Mapping[RunStatus, frozenset[RunStatus]] = MappingProxyType({
       RunStatus.RECEIVED: frozenset({RunStatus.VALIDATED, RunStatus.BLOCKED,
                                      RunStatus.FAILED, RunStatus.CANCELLED}),
       RunStatus.VALIDATED: frozenset({RunStatus.RUNNING, RunStatus.BLOCKED,
                                       RunStatus.FAILED, RunStatus.CANCELLED}),
       RunStatus.RUNNING: frozenset({RunStatus.RUNNING, RunStatus.WAITING_HUMAN,
                                     RunStatus.SUCCEEDED, RunStatus.DEGRADED,
                                     RunStatus.BLOCKED, RunStatus.FAILED,
                                     RunStatus.CANCELLED}),
       RunStatus.WAITING_HUMAN: frozenset({RunStatus.RUNNING, RunStatus.BLOCKED,
                                           RunStatus.FAILED, RunStatus.CANCELLED}),
       RunStatus.SUCCEEDED: frozenset(),
       RunStatus.DEGRADED: frozenset(),
       RunStatus.BLOCKED: frozenset(),
       RunStatus.FAILED: frozenset(),
       RunStatus.CANCELLED: frozenset(),
   })
   ```

   同样为 `GateStatus`、`CommandStatus`、`ActionStatus` 建表。
   提供：

   ```python
   class IllegalTransition(RuntimeError):
       """code == ErrorCode.RUNTIME_ILLEGAL_TRANSITION"""

   def ensure_run_transition(current: RunStatus, target: RunStatus) -> None: ...
   # gate/command/action 各一个同型函数
   ```

3. 在引擎的每个状态写入点前调用对应 `ensure_*`。跑全量测试；
   若某测试暴露表中缺失的合法迁移，把该迁移补进表**并在表旁注释
   出现场景**，不允许为通过测试而放宽成"全部允许"。
4. `ErrorCode` 新增成员 → 同步 `tests/contract/test_public_models.py`
   与 `error_catalog.py`；运行 `make contracts` 检查 openapi 是否受影响
   （ErrorCode 若出现在 openapi enum 中则提交更新）。

**新增测试**：迁移表本身的性质测试——终态无出边；表覆盖全部 enum 成员；
`ensure_run_transition(SUCCEEDED, RUNNING)` 抛 `IllegalTransition`。

**验收**：`make lint && make test && make test-services`。此为 **里程碑 M3**。

### B2 抽取 `CommandExecutor`

**新增文件**：`src/gaia/runtime/command_execution.py`。
**修改**：`persistent_engine.py`。

**步骤**：

1. 把以下方法原样搬入 `CommandExecutor` 类（构造参数：
   `dependencies: RuntimeDependencies` + 事件追加/步骤记录所需的回调或
   共享协作对象，侦察后选择最小耦合方案；推荐把 `_append_event`、
   `_record_step` 先提为引擎上的公开协作对象再注入）：
   - `_create_approved_command`、`_execute_command`、`_guard_tool_value`、
     `_mark_command_unknown`、`_store_command_result`、
     `_command_envelope`、`_command_parts`。
2. 引擎持有 `self._commands = CommandExecutor(...)`，原方法体改为委托。
   方法签名、事件顺序、事务边界（session 的传入方式）不变。

**验收**：`make lint && make test && make test-services`，
现有测试零断言改动。

### B3 抽取 `ActionPlanManager`

同 B2 模式。**新增文件**：`src/gaia/runtime/action_plan.py`。
搬移：`_start_action_plan`、`_advance_action_plan`、`_action_record`、
`_proposal_from_action`、`_update_plan_action`、`_complete_plan_action`、
`_fail_plan_action`、`_public_action_plan`。

**验收**：同 B2。

### B4 抽取 `HandoffCoordinator` 与恢复逻辑

同 B2 模式。**新增文件**：`src/gaia/runtime/handoff.py`。
搬移：`_resolve_handoffs`、`_persist_handoff`、`_clear_handoff`、
`_recover_handoff`、`_runtime_handoff`。
恢复逻辑（`startup_recover`、`_ensure_active_run_budgets`）留在引擎
（工程 D 会动它，避免连环冲突）。

**验收**：同 B2。

### B5 收尾度量与文档

1. **规模目标修正（2026-07-27，基于 B2–B4 实测）**：本卡原写"降到 800 行以下"。
   实测 B2/B3/B4 分别搬走 393/341/142 行，引擎从 1980 降到 **1146**，
   且搬移是彻底的——三个协作者文件里没有重复留存的方法体（已用
   `grep -c "async def _resolve_handoffs\|..."` 核对为 0）。

   剩余 30 个方法的构成：10 个公开 API（`create`/`decide`/`cancel`/
   `transition`/`inspect`/`events_after`/`startup_recover`/`get_gate`/
   `get_command`/`side_effect_success_count`）、6 个核心编排
   （`_apply_outcome`/`_resume_continuation`/`_create_received`/
   `_idempotent_run`/`_finish`/`_create_gate`）、12 个被三个协作者共用的
   账本管道、以及预算与恢复各一。前两组是引擎的本职，**不应再拆**——
   为凑数字硬拆只会把耦合藏进新文件，违背工程 B"让人敢改"的初衷。

   因此把目标改为：**B5 结束时 ≤1200 行，且三个协作者各自独立可读**。
   真正还能降的是那 12 个账本管道方法，但那不是"再切一刀"，而是与
   既有的 `RuntimeLedger` 合并——见新增的 B6。

   仍然要做的断言性检查：确认被搬走的方法在引擎中不存在残留副本。

   **后续更新（F6，2026-07-28）**：C2 在引擎里新增了租约续租逻辑，D1 新增了
   `startup_recover` 的恢复批处理循环，两者都是核心编排的一部分（不是可抽走
   的独立协作者），实测行数因此回升到 **1306** 行，超过上面刚定的 ≤1200。
   不为了把数字压回 1200 再拆一刀——本卡第 1 点已经论证过，剩下的公开 API
   和核心编排方法拆出去只会把耦合藏进新文件，不会减少耦合，工程 A/B 的目标
   是"让人敢改"而不是"文件更小"。**结论：≤1200 不再是本仓库对
   `persistent_engine.py` 的强制上限；1306 是当前的实测值，之后每次真的往
   引擎里加编排逻辑，行数还会再涨，这本身不是需要修的问题**——除非新增的
   内容明显是可抽出的独立协作者（像 B2–B4 那样），否则不要为了对齐某个历史
   数字而拆分。
2. 更新 `docs/施工图/02-Runtime状态机与事务边界.md`：加一节
   "状态机的代码权威位置是 `runtime/lifecycle.py`，本文档描述性内容
   与其冲突时以代码为准"。
3. `docs/施工图/实现状态.md` 登记。

**验收**：`make lint && make test && make test-services`。此为 **里程碑 M4**。

### B6 合并账本：消除 RuntimeLedger 与引擎私有管道的双份实现（B5 侦察催生）

**发现**：`src/gaia/runtime/ledger.py` 定义了 `RuntimeLedger`，提供
`append_event`、`event`、`create_run`、`get_run`、`add_gate`、`add_command`
——正是引擎私有管道在做的事。但**生产代码从不使用它**：全库引用只有
`tests/integration/test_persistence.py` 一处。引擎自己另有
`_append_event`、`_record_step`、`_record_failure_event`、`_transition`、
`_snapshot`、`_gate`、`_event` 等一套并行实现。

这与工程 A 治理的是同一种病：**同一件事有两份实现，其中一份没人用、
必然腐烂**。而且 `RuntimeLedger` 顶着一个权威名字，会误导后来者以为
它就是事实来源。

**这不是可选清理**：B1 让状态迁移有了唯一权威表，但"事件与快照如何落库"
仍是散的；不合并，工程 B"引擎可被逐模块理解"的目标只完成一半。

**步骤**：

1. **先判定去留**。对比 `RuntimeLedger` 与引擎私有管道的能力差集，
   决定是"引擎改用 RuntimeLedger"还是"RuntimeLedger 并入引擎的实现后删除"。
   判据是哪一侧的事务边界与事件序号语义更完整——**读代码得出结论，
   不要凭名字选**。把判断写进提交说明。
2. 落地合并，保持纯搬移：事件顺序、序号分配、事务边界不得改变。
3. 若选择保留 `RuntimeLedger`，让三个协作者也经它落库，
   使"事件与快照的唯一落库路径"成为可验证的性质；
   若选择删除，同步删掉那个只为它存在的测试引用（改测真实路径）。
4. 自检：`grep -rn "RuntimeLedger" src/ tests/` 的结果必须与所选方案一致，
   不允许出现"生产不用、测试仍在用"的中间态。

**验收**：`make lint && make test && make test-services`；
现有断言零改动；引擎行数变化作为观测值记录，不作为目标。

---

## 5. 工程 C：版本指纹与策略收紧覆盖（P1）

### C1 内容指纹 `gaia.sdk.versioning`

**新增文件**：`src/gaia/sdk/versioning.py`、`tests/unit/test_versioning.py`。
**修改**：`src/gaia/sdk/__init__.py`（导出）、`src/gaia/testing/gates.py`
（新增 Gate）、`examples/function_task/flows.py`（示范用法）、
`developer-docs/`（相应指南页）。

**步骤**：

1. 实现：

   ```python
   def fingerprint(*sources: object, length: int = 12, qualified: bool = True) -> str:
       """Deterministic content version.

       qualified=True  -> 'sha256:3f1a9c0d2e4b'   (human-facing, self-describing)
       qualified=False -> '3f1a9c0d2e4b'          (embeddable in a version string)

       Accepts: pathlib.Path / str path -> file bytes;
       module / class / function -> inspect.getsource;
       Mapping / Sequence -> canonical JSON (sort_keys, compact)."""
   ```

   **`qualified` 参数是必须的，不是可选设计**：带前缀的
   `sha256:3f1a9c0d2e4b` 含冒号，拼进版本号会得到
   `1.0.0+ovr.sha256:3f1a9c0d2e4b`——冒号不属于 PEP 440 local version
   允许的字符集（只允许字母数字和点），这个串既非法也不好解析。
   C2 拼接版本号时必须用 `qualified=False`。
   `length` 默认 12，取值范围校验 `8 <= length <= 64`。

   两处用法示例（文档里都要给）：

   ```python
   rules_version = fingerprint(rules)                    # 'sha256:3f1a9c0d2e4b'
   digest       = fingerprint(payload, qualified=False)  # '3f1a9c0d2e4b'
   ```

   多个 source 时对各自摘要拼接后再摘要。文件不存在、取不到 source 时抛
   `ValueError`，不静默。
2. 用法（写进 docstring 与文档）：

   ```python
   from examples.function_task import rules

   @scenario("order-review", rules_version=fingerprint(rules), ...)
   ```

   规则内容一变，`rules_version` 自动变，审计证据里的 `VersionBundle`
   不再撒谎。
3. `testing/gates.py` 新增 `VersionBundleGate`（先读该文件的 Gate 协议）：
   构造参数 `expected: Mapping[str, str]`（字段名 → 期望版本），
   对 Run 快照的 `VersionBundle` 做精确比对，不匹配即 Gate 失败——
   给企业一个"版本变了必须显式确认"的 CI 钩子。
4. `examples/function_task` 至少一个场景改用 `fingerprint`。

**验收**：`make lint && make test`。

### C2 策略收紧覆盖（monotonic policy override）

**前置**：**A3 + C1**。A3 提供唯一的覆盖应用点 `RuntimeAssembler`
（一次接入即对所有装配路径生效）；C1 提供 `fingerprint(..., qualified=False)`，
是本任务版本证据的依赖。两者缺一不可，不要在 C1 之前开工 C2。

**改动文件**：`src/gaia/config/models.py`、`src/gaia/runtime/policy.py`、
`src/gaia/runtime/assembly.py`、`src/gaia/contracts/models.py`
（`ErrorCode` 新增 `POLICY_OVERRIDE_INVALID`）、`error_catalog.py`、
`tests/unit/test_policy_override.py`。

**步骤**：

1. 配置模型（`config/models.py`）：

   ```python
   class PolicyOverrideSettings(StrictModel):
       write_mode: WriteMode | None = None
       max_steps: int | None = None
       max_model_calls: int | None = None
       max_duration_seconds: int | None = None
       deny_tools: tuple[str, ...] = ()
   ```

   `RuntimeSettings` 新增
   `policy_overrides: Mapping[str, PolicyOverrideSettings] = {}`（key 为
   scenario_id）。注意 `WriteMode` 定义在 `contracts/models.py`，config
   模块 import 它是否会造成环依赖——**侦察**：`grep -n "import" src/gaia/config/models.py`；
   若有环，就在 config 内定义同值 StrEnum 并在装配处转换。
2. `runtime/policy.py` 新增纯函数：

   ```python
   def apply_policy_override(
       policy: ExecutionPolicy, override: PolicyOverrideSettings
   ) -> ExecutionPolicy:
       """Return a strictly tighter policy whose version carries the override
       fingerprint, so that audit evidence changes whenever governance changes."""
   ```

   规则（**只收紧**，任何放宽立即抛错，fail fast 于应用启动期）：
   - `write_mode`：仅当比现值更严格才接受（严格序 DISABLED <
     APPROVAL_REQUIRED < ENABLED；把 `safety.py` 的 `_stricter_write_mode`
     的秩表复制到 policy.py 为公共函数 `stricter_write_mode`，
     `safety.py` 改为从 policy.py 导入——这是本施工图唯一允许触碰
     safety.py 的动作，且仅限 import 来源变更）；
   - `max_*`：仅接受更小值；
   - `deny_tools`：从 `allowed_tools` 移除，不存在的名字忽略；
   - 违反任一规则抛 `ValueError`，消息前缀 `POLICY_OVERRIDE_INVALID:`。

   **版本证据规则（关键，不可省略）**：覆盖生效后返回的 `ExecutionPolicy`
   必须携带 effective policy fingerprint，否则会出现"实际策略已收紧、
   审计版本却没变"的证据失真——这正是工程 C 要消灭的问题。做法：

   ```python
   digest = fingerprint(override_payload, qualified=False)   # 无 'sha256:' 前缀
   effective_version = f"{policy.version}+ovr.{digest}"      # PEP 440 合法
   ```

   其中 `override_payload` 是**规范化后实际生效的覆盖项**
   （只含真正改变了策略的字段，按 key 排序的 canonical JSON），
   `fingerprint` 复用 C1 的 `gaia.sdk.versioning.fingerprint`。
   **必须传 `qualified=False`**：带前缀的 `sha256:...` 含冒号，
   拼出的 `1.0.0+ovr.sha256:3f1a...` 不是合法的 PEP 440 local version。
   为此加一条断言测试：`"+ovr." in v and ":" not in v.split("+", 1)[1]`。
   覆盖存在但未改变任何值（例如 override 与基线完全相同）时，
   `effective_version` 保持原值不变——指纹只反映实质差异。
   `policy_id` 不变，只有 `version` 变。

3. 应用点：`RuntimeAssembler.create_engine` 内，构造
   `FunctionScenarioRunner` 后，若该 scenario_id 存在 override，用代理包装：

   ```python
   class OverriddenRunner:
       """Delegates to the inner runner with a tightened, fingerprinted policy."""
       # execution_policy 返回 apply_policy_override(...) 的结果；
       # version_bundle 返回 inner.version_bundle.model_copy(update={
       #     "policy": f"{p.policy_id}:{p.version}"   # p = 覆盖后的 policy
       # })，即 policy 版本证据随覆盖一起变化；
       # run/run_handoff/run_continuation/bind_gate/resume 全部委托。
   ```

   两者用同一个覆盖后的 policy 推导，`RuntimeDependencies.__post_init__`
   的一致性校验（`version_bundle.policy == f"{policy_id}:{version}"`）
   自动满足，**不需要也不允许放宽该校验**。

   由此得到的性质：Run 落库时 `VersionBundle.policy` 形如
   `policy-order-review:1.0.0+ovr.9c1d2f0a3b44`。运维侧改一条 override →
   指纹变化 → 该时间点之后所有 Run 的审计证据可与之前区分；
   C1 的 `VersionBundleGate` 也会因此失败，迫使变更被显式确认。

4. 测试：
   - 收紧生效（write_mode 收紧后走 HumanGate）；
   - 放宽被拒（启动即抛 `POLICY_OVERRIDE_INVALID`）；
   - `deny_tools` 后工具调用被 `TOOL_NOT_ALLOWED` 拦截；
   - 无 override 时零行为变化，且 `VersionBundle.policy` **不含** `+ovr.`；
   - **证据用例**：同一场景，有无 override 两次 Run 落库的
     `VersionBundle.policy` 不相等；改动 override 内容后指纹再次变化；
     override 内容不变时指纹稳定（可重复构造两次断言相等）。

**验收**：`make lint && make test`。此为 **里程碑 M5**。

---

## 6. 工程 D：恢复租约与部署边界（P2）

### D1 恢复租约

**新增文件**：`src/gaia/persistence/leases.py`、
`src/gaia/persistence/migrations/versions/0014_runtime_leases.py`、
`tests/unit/test_leases.py`。
**修改**：`src/gaia/persistence/models.py`（新表 ORM）、
`persistent_engine.py` 的 `startup_recover`。

**步骤**：

1. 迁移 0014（先读 0013 的写法照抄格式；`down_revision` 指向 0013）：

   ```text
   runtime_leases(
     name        VARCHAR PRIMARY KEY,
     owner       VARCHAR NOT NULL,
     expires_at  TIMESTAMP(tz) NOT NULL
   )
   ```

2. `leases.py`：

   ```python
   class LeaseLost(RuntimeError):
       """The lease expired or was taken over while work was still running."""


   class LeaseStore:
       def __init__(self, session_factory): ...
       async def try_acquire(self, name: str, owner: str, ttl_seconds: int) -> bool: ...
       async def renew(self, name: str, owner: str, ttl_seconds: int) -> bool: ...
       async def release(self, name: str, owner: str) -> None: ...
   ```

   `try_acquire` 语义：行不存在 → INSERT 成功获得；行存在且
   `expires_at < now` 或 `owner` 相同 → UPDATE 续期获得；否则 False。
   `renew` 语义：仅当 `owner` 匹配**且尚未过期**时把 `expires_at` 推后并
   返回 True；否则返回 False（表示租约已丢失，绝不重新抢占——
   一旦过期就可能已有另一副本接管，静默续期会造成双执行）。
   实现用单条带 WHERE 的 UPDATE + 受影响行数判断，INSERT 冲突时回退判定
   （SQLite 与 PostgreSQL 都要过；参考 `capabilities/outbox.py` 里
   租约领取的现成写法保持风格一致）。

3. **恢复必须是有界批次 + 心跳续租**（固定 TTL 单批全量恢复是错的：
   恢复任务量不可预测，300 秒可能在任务未完成时到期，届时另一副本接管
   会造成同一批 Run 被重复恢复）。改造 `startup_recover`
   （当前 `persistent_engine.py` 约 633 行，两段 `select` 分别取
   handoff runs 与 commands，然后各自整体 for 循环）：

   - 常量：`_RECOVERY_LEASE_TTL_SECONDS = 60`、`_RECOVERY_BATCH_SIZE = 50`、
     `_RECOVERY_RENEW_EVERY = 10`（每处理 10 个条目续租一次；
     续租周期必须显著小于 TTL）；
   - `owner = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"`
     （加随机段，避免同主机 PID 复用导致误判为同一持有者）；
   - `try_acquire("runtime-recovery", owner, ttl_seconds=60)` 失败 →
     记 warning 日志并返回 `[]`；
   - 两段查询都加**稳定排序** `.order_by(RunRecord.run_id)` /
     `.order_by(SideEffectCommandRecord.command_id)` 再
     `.limit(_RECOVERY_BATCH_SIZE)`。**排序不是可选项**：没有确定序时，
     数据库返回顺序不保证，反复失败的记录可能每批都占据前 50 条，
     导致后面本可恢复的记录永远轮不到——这是一个静默的可用性故障。
     配合下面的游标推进（`WHERE run_id > last_seen`）保证严格前进；
   - 外层改为循环：取一批 → 逐个处理，
     每 `_RECOVERY_RENEW_EVERY` 个调用一次 `renew`；
     `renew` 返回 False → 立即停止恢复，记 warning，返回**已完成的部分**
     （不抛异常打断应用启动，也绝不继续处理——这是关键的安全选择）；
     本批处理完后若返回条数等于 batch size 则继续取下一批，否则结束；
   - 循环必须有终止保证：用**游标推进**（记住本批最后一个 id，
     下批 `WHERE id > cursor`）而不是重复查同一个集合；
     同时保留兜底——若某批处理后待恢复集合没有缩小且游标未前进，
     记 error 并退出循环，避免无限循环把启动卡死；
   - 全部完成后 `release`；异常路径用 `try/finally` 保证 `release`。

#### D1.1 不可自动恢复的 Command 必须离开候选集

**问题**：`startup_recover` 的 command 查询包含
`CommandStatus.UNKNOWN`。UNKNOWN 表示写入结果不确定（已发出但未确认），
需要 reconcile。若某个 UNKNOWN command 的 reconcile 永久失败
（下游系统已不可达、Adapter 已下线），它会**每次启动都被重试**，
永久占据恢复批次并拖慢每一次启动——排序和游标只是让它不再阻塞别人，
不能让它自己消失。

**必读锚点**：`_execute_command`（`persistent_engine.py` 约 1411–1440 行）
**已经**按 `WriteRecoveryStrategy` 分支处理了 `reconcile_only` 路径：

| 策略 | 现有 reconcile 行为 |
| --- | --- |
| `RECONCILABLE` | 调 `adapter.reconcile()`；返回 `None` 则 `_mark_command_unknown` |
| `IDEMPOTENT` | 用原 `command_key` 重放 `adapter.execute()` |
| `AT_MOST_ONCE_MANUAL` | **直接** `_mark_command_unknown`，不重放 |

本任务是在这个**已有分支之上**加"何时停止重试"，不是新造一套策略判断。

**做法**：

1. `contracts/models.py` `CommandStatus` 新增终态成员
   `NEEDS_ATTENTION = "needs_attention"`（同步
   `tests/contract/test_public_models.py`、`error_catalog.py`，
   并检查 openapi 是否含该 enum → 需要则 `make contracts`）；
2. `persistence/models.py` 的 command 记录增加
   `recovery_attempts: int`（默认 0）；迁移 0014 一并加列
   （与 `runtime_leases` 表同一个 revision，避免两个迁移互相依赖）；
3. **按策略决定重试预算（关键，不可统一处理）**：

   | 策略 | 恢复预算 | 到达上限后 |
   | --- | --- | --- |
   | `RECONCILABLE` | 最多 `_RECOVERY_MAX_ATTEMPTS = 3` 次 reconcile | `NEEDS_ATTENTION` |
   | `IDEMPOTENT` | 最多 3 次用**原 command_key** 重放 | `NEEDS_ATTENTION` |
   | `AT_MOST_ONCE_MANUAL` | **0 次**：首次结果不明即终止 | 立即 `NEEDS_ATTENTION` |

   `AT_MOST_ONCE_MANUAL` 的语义就是"最多执行一次，之后必须人工介入"。
   对它做 3 次尝试是**危险的**——即使当前实现不重放 execute，让它反复
   停留在恢复候选集里也违背语义，且每次启动都要重新走一遍判断。
   实现上：`_mark_command_unknown` 时若策略为 `AT_MOST_ONCE_MANUAL`，
   直接置 `NEEDS_ATTENTION` 而不是 `UNKNOWN`；
   另两种策略在 `recovery_attempts` 达到 3 时转 `NEEDS_ATTENTION`。
   转换时都要写一条 Run 事件（actor=SYSTEM）说明策略与原因，
   **并从恢复查询的 status 过滤中排除 `NEEDS_ATTENTION`**；
4. 与 B1 的状态迁移表对齐：`CommandStatus` 迁移表加入
   `UNKNOWN → NEEDS_ATTENTION` 与 `EXECUTING → NEEDS_ATTENTION`
   （`AT_MOST_ONCE_MANUAL` 首次即转的路径），`NEEDS_ATTENTION` 为终态
   无出边（若 B1 已完成则直接改表；若 D1 先于 B1 完成，在 B1 建表时补上）；
5. Actuator 的运行摘要（README 提到的 24 小时 Run 摘要）增加
   `needs_attention` 计数，让它可被运维发现——**进入人工处理状态而
   不被看见，等于换了一种方式丢失问题**。

**`NEEDS_ATTENTION` 的能力边界（必须写进文档，避免误解）**：
它当前**只是一个不可自动恢复的终态 + 运维可见标记**。本次
**不提供**框架内的人工处置 API——没有"在 Console 里改写 Command 状态"
或"手动标记为已完成"的入口。人工处置意味着有人在下游系统核对真实结果
后修改 Gaia 的权威记录，这需要独立的授权模型、审计链路和幂等语义，
是一个独立议题。文档中不得暗示 Dev Console 可以继续处置这类 Command，
口吻对齐 `09-Runtime安全边界与Sandbox.md`。

**测试**：
- `RECONCILABLE` 连续失败 3 次后变 `NEEDS_ATTENTION`，第 3 次之前
  仍留在候选集；
- `IDEMPOTENT` 同上，且重放使用的是原 `command_key`；
- **`AT_MOST_ONCE_MANUAL` 首次结果不明即变 `NEEDS_ATTENTION`，
  且 `adapter.execute` 的调用次数恰为 1**（这条是安全性断言，必须有）；
- 三种情况下后续 `startup_recover` 都不再取到该 command；
- 摘要计数正确。

4. 测试：
   - 双 store 并发 `try_acquire` 只有一个成功；
   - 过期后可被另一 owner 抢占；
   - `renew` 在 owner 匹配且未过期时成功；owner 不匹配时失败；
     **已过期时失败**（不得自动重新抢占）；
   - **批次用例**：构造多于 `_RECOVERY_BATCH_SIZE` 的待恢复 Run，
     断言全部被恢复且期间发生过 `renew`；
   - **租约丢失用例**：注入一个第 N 次返回 False 的 `renew`，断言恢复
     提前停止、返回已完成部分、不抛异常、剩余条目未被处理；
   - `postgres` mark 下跑一遍（`make test-services`）。

**验收**：`make lint && make test && make test-services`。

### D2 部署拓扑边界声明

**改动文件**：`README.md`、`developer-docs/mechanisms.md`（或
developer-guide 中最合适的运行章节，侦察后选择）、
`docs/施工图/09-Runtime安全边界与Sandbox.md`（追加一节）。

**内容要点**（照写）：

- SQLite 档：单进程单副本，是开发与小规模默认档；
- PostgreSQL 档：API 服务可多副本，但当前版本的 Runtime 恢复由租约
  保证同一时刻单副本执行；Outbox dispatcher 依赖租约领取，天然多副本安全；
- 明确"当前不提供跨副本的 Run 级并发执行协调"，这是已知边界而非缺陷；
- 与 09 号文档的 Sandbox 边界声明保持同一口吻。

**验收**：`uv run mkdocs build --strict`。此为 **里程碑 M6**。

---

## 7. 工程 E：清理项（P3）

### E1 类型化组件访问与错误码统一

**改动文件**：`src/gaia/application/core.py`、`error_catalog.py`、
相关单测。

1. `get_component` 增加重载：

   ```python
   def get_component(self, component_id: str, expected: type[T] | None = None) -> Any | T:
   ```

   `expected` 给定且实例不匹配时抛带错误码的 `TypeError`
   （`COMPONENT_TYPE_MISMATCH`）。
2. 现有 `RuntimeError("APPLICATION_NOT_STARTED")` 与
   `KeyError(f"COMPONENT_NOT_FOUND:...")` 保持字符串码不变，但两个码
   登记进 `error_catalog.py`（含操作建议），消除"体系外错误"。
3. `api/devtools_prompts.py` 与 A4 的 `_optional_component` 改用带
   `expected` 的调用。

### E2 `framework_version` 去硬编码

**改动文件**：`src/gaia/application/core.py`（约 125 行）及
`grep -rn '"0.1.0"' src/` 找到的其他硬编码点。

```python
from importlib.metadata import PackageNotFoundError, version

def _framework_version() -> str:
    try:
        return version("gaia-framework")
    except PackageNotFoundError:
        return "0.0.0+dev"
```

注意 `tests/contract/` 中若有对 `framework_version == "0.1.0"` 的断言，
改为断言语义（非空、符合 PEP 440）而不是具体值。

### E3 认证 SPI 占位

**新增文件**：`src/gaia/sdk/auth.py`。

```python
class AuthenticationError(Exception):
    """Credentials are missing, malformed, or rejected."""


class AuthnProvider(Protocol):
    """Resolve the caller identity for one HTTP request.

    Three outcomes, deliberately distinct:
      raise AuthenticationError -> authentication FAILED; reject the request (401).
      return UserIdentity       -> authenticated AND carries an end-user identity;
                                   this identity is the single source of truth.
      return None               -> authenticated as a TRUSTED SERVICE with no
                                   end-user identity; RunRequest.user applies.
    """
    async def authenticate(self, headers: Mapping[str, str]) -> UserIdentity | None: ...
```

**三态语义必须在 E3 实施前固定**（这是本任务的第一步，先定语义再写码）：
若用 `None` 同时表示"认证失败"和"已认证但无用户身份"，两种情况会被
同一段代码处理——而它们的正确响应截然相反：前者必须拒绝（401），
后者必须放行并沿用 `RunRequest.user`。合并语义迟早会导致认证失败被
当成可信服务调用放行，这是最坏的一类故障。因此用**异常**表达失败，
用**返回值**表达身份有无。

提供 `ApiKeyAuthnProvider` 默认实现（现有 api_key 逻辑搬入），
`create_app` 增加可选参数 `authn: AuthnProvider | None = None`，
缺省行为与现状完全一致。**只留口子，不做 SSO。**

**身份权威规则（必须写进 Protocol docstring 与 `developer-docs/`）**：
`AuthnProvider` 解析出的身份是**唯一事实源**。客户端在
`RunRequest.user` 里提交的 `user_id` / `roles` 是不可信输入
——`roles` 直接参与 `safety.py` 的 `validate_roles` 和工具
`required_roles` 校验，允许客户端自称角色等于让调用方自己给自己授权，
整个受控执行体系就此失效。

因此规定：

- `authenticate` 抛 `AuthenticationError` → 返回 401，不进入 Runtime；
- 返回 `UserIdentity` → 它是**唯一事实源**，覆盖 `RunRequest.user`，
  不做字段合并；若请求体中的 `user` 与之不一致，**拒绝请求**而不是
  静默覆盖（静默覆盖会让调用方以为自己以另一身份执行了操作），
  错误码新增 `IDENTITY_MISMATCH`，登记 error_catalog；
- 返回 `None` → 可信服务调用，`RunRequest.user` 生效，行为同现状；
- 默认的 `ApiKeyAuthnProvider` 校验 Key 后返回 `None`（Key 不对则抛
  `AuthenticationError`）。这是已知的信任边界：
  **API Key 模式假定调用方是可信的服务端，由它负责终端用户身份的真实性**，
  这句话要明确写进文档，与 `09-Runtime安全边界与Sandbox.md`
  的诚实表述口吻一致；
- 本任务只实现语义、规则与默认实现，不实现任何具体 SSO 集成。

涉及公共 API 面 → 运行 `make contracts` 并提交 openapi 变更（若有）。

**测试**：三态各一条——抛 `AuthenticationError` 返回 401；
返回 `UserIdentity` 时覆盖生效；返回 `None` 时 `RunRequest.user` 生效；
请求体身份与认证身份冲突时返回 `IDENTITY_MISMATCH`；
未配置 `authn` 时行为与改动前逐字节一致。

**验收（E1–E3 各自）**：`make lint && make test`。

---

## 8. 里程碑总验收清单

每个里程碑（M1、M2、M4、M5、M6）达成时执行：

```bash
make lint
make test
make test-services        # 需要本地 docker compose 起 postgres/redis：
                          # docker compose -f infra/dev/compose.yaml up -d
make contracts            # openapi 与生成契约无未提交漂移
uv run mkdocs build --strict
uv run gaia init /tmp/gaia-ms-check && (cd /tmp/gaia-ms-check && uv run gaia check)  # M2 起
```

全部工程完成后的终态断言：

1. `examples/function_task/app.py` ≤ 15 行，无任何手工 Runtime 组装，
   **且该应用已覆盖 handoff（含 agent → agent 逐跳路由）与 continuation
   两条路径**——即高级应用同样不需要手工 Builder；
2. `grep -rn "PersistentRuntimeEngine(" src/ examples/` 除
   `runtime/assembly.py` 与 `examples/controlled_task`（自定义 SPI 例外）
   外无命中，装配只有一处实现；
3. `actuator_snapshot()` 组件列表包含 `runtime-assembler`，
   Dev Console 组件页展示的图与实际执行路径同源；
4. Scenario 模块顶层做 I/O（读 Secret / 建连接）时 `gaia check` 返回
   退出码 2 并给出行号级 findings；**全仓库无任何对
   `socket` / `resolve_secret` 的运行时 monkeypatch**
   （`grep -rn "patch(.*socket\|patch(.*resolve_secret" src/` 无命中）；
5. `persistent_engine.py`（原定 <800，按 B5 实测修正为 ≤1200；C2 的租约逻辑与
   D1 的恢复批处理循环之后又把行数推高到实测 **1306** 行——不为对齐数字再拆
   一刀，理由见 B5 卡与 F6 卡：继续拆只会把耦合藏进新文件，不是消除耦合）
   状态迁移唯一权威在 `runtime/lifecycle.py`，事件落库无双份实现；
6. 配置里对任意场景加一条放宽性 `policy_overrides` → 应用启动失败并给出
   `POLICY_OVERRIDE_INVALID`；
7. 加一条**收紧性** `policy_overrides` → 应用正常启动，且该场景之后所有
   Run 的 `VersionBundle.policy` 带 `+ovr.<digest>` 后缀（**不含冒号，
   PEP 440 合法**），与覆盖前的 Run 可区分；移除覆盖后后缀消失；
8. 两个进程同时 `startup_recover` 同一数据库 → 恰好一个执行恢复；
   待恢复条目数超过一个批次时仍能全部完成，且期间发生续租；
   续租失败时恢复安全地提前停止，不重复处理；恢复查询有稳定排序与
   游标推进，反复失败的记录不会饿死后续记录；
9. 连续 3 次无法 reconcile 的 UNKNOWN command 进入 `NEEDS_ATTENTION`
   终态，离开恢复候选集，且在运行摘要中可见；
10. 配置了 `AuthnProvider` 时，请求体 `user` 与认证身份冲突返回
    `IDENTITY_MISMATCH`；未配置时行为与改动前一致；
11. `docs/施工图/实现状态.md` 已登记 A–E 各工程状态与基线 commit。

## 8b. 工程 F：评审整改（2026-07-28 阻断项）

外部评审判定"不能按重构完成验收"，4 项阻断 + 1 项 P2。本节是整改任务卡。
**工程 F 全部完成前，本施工图不得标记为完成。**

### F1 认证身份必须贯穿所有接口，审批人由服务端生成（P0）

**已复现的漏洞**（`examples/function_task`，`X-Gaia-Api-Key` 认证下）：

```
1. Alice 创建受控写入 -> waiting_human, gate 6cdd83d8...
2. Bob（无归属关系）读取 Alice 的 Gate -> 200
3. Bob 请求体伪造 roles=["approver"], decided_by="mallory" -> 200 succeeded
```

**根因**：`api/app.py` 的 `authorize()` 只返回错误、**丢弃** `authenticate()` 得到的身份；
除 `create_run` 外所有接口都用它，因此既不校验资源归属也不校验真实角色。
`HumanGateDecisionRequest`（`contracts/models.py`）的 `decided_by` / `roles` 由客户端提供，
其校验器只要求 `"approver" in roles`——而那个字段正是攻击者控制的。

E3 声明了"认证身份是唯一事实源"，却只在 `create_run` 落实。**规则写了但没贯彻，
比没写更危险**：它让审计记录看起来有授权依据，实际依据是调用方的自述。

**步骤**：

1. `authorize` 改为向下游传递 `UserIdentity | None`，而不是丢弃。所有受保护接口
   （Run 读取/取消、Gate 读取/审批、Command 查询、诊断、SSE）都要拿到它。
2. **审批人与角色由服务端生成**：`decide` 使用认证身份的 `id` 与 `roles`，
   忽略请求体中的 `decided_by` / `roles`。二者不一致时按 E3 的既有规则返回
   `IDENTITY_MISMATCH`，不静默覆盖。
   兼容处理：无认证身份（API Key 可信服务模式）时保留请求体语义，
   但必须在文档中写明这是**信任调用方**的模式。
3. **资源归属校验**：读取/取消 Run、读取/审批 Gate 时，认证身份的 `organization`
   必须与 Run 的 `user.organization` 一致，否则 404（不用 403，避免泄露资源存在性）。
   跨组织访问是企业场景的基本隔离。
4. 契约变更：`HumanGateDecisionRequest` 的 `decided_by` / `roles` 在有认证身份时
   不再是权威来源。评估是否将其改为可选字段；若改动公共契约需 `make contracts`。

**验收**：上述复现脚本三步中，第 2 步返回 404、第 3 步返回 403/IDENTITY_MISMATCH；
新增测试覆盖跨组织读取、伪造角色审批、以及无认证身份时的兼容路径。

### F2 内置 OIDC/JWT AuthnProvider（企业 IAM 对接）

**定位**：框架**不做身份系统**。企业已有 IdP（Keycloak / Okta / Entra ID / Ping），
Gaia 只消费它们签发的凭证。E3 的 `AuthnProvider` 接缝已就位，缺标准协议实现。

**步骤**：

1. `JwtAuthnProvider`：Bearer token，JWKS 取公钥并缓存（带 TTL 与失败退避），
   校验 `iss` / `aud` / `exp` / `nbf`、**算法白名单**（禁 `none`，禁对称算法混用）。
2. **claim 映射必须可配置**——各家 IdP 放角色的位置不同（Keycloak 在
   `realm_access.roles`、Entra 在 `groups`、Okta 常为自定义 claim）。写死任何一种
   都会让框架只能对接一家。配置形如：

   ```yaml
   authn:
     provider: oidc
     issuer: https://idp.example.com/realms/gaia
     audience: gaia-api
     jwks_url: ...            # 缺省从 issuer 的 discovery 文档推导
     claims:
       subject: sub
       organization: org_id
       roles: realm_access.roles     # 支持点号路径
   ```

3. 依赖放 extras（如 `gaia-framework[oidc]`），不进默认安装。
4. 文档写明**边界**：Gaia 校验令牌真伪并映射身份；令牌签发、用户生命周期、
   角色授予属于 IdP。口吻对齐 09 号文档。

**验收**：用本地生成的密钥对签发令牌做端到端测试——有效令牌通过、过期/错 audience/
错 issuer/`alg=none`/错签名分别被拒；claim 映射对三种典型 IdP 布局各一个用例。

### F3 `make verify` 的发布闸门失败（P1）

`scripts/package_smoke.py` 在**安装生成项目之前**就跑 `gaia check`，而声明式装配后
`gaia check` 会 import `scenarios.modules`，因此必然报
`SCENARIO_MODULE_NOT_FOUND:ci_smoke.scenarios.hello`。

修法：smoke 流程改为先安装生成项目再 check，并把"生成项目必须先安装才能 check"
固定为脚手架契约（A7 已在 `gaia init` 输出和生成的 README 里写了这一步，
package_smoke 是唯一没遵守的地方）。

### F4 实现 A2.1 的 AST 导入期纯净性检查（P1）

施工图标为必做，至今只有契约文档。缺失：`diagnostics/import_purity.py`、
`scan_module_purity`、`PurityFinding`、对应测试、`gaia check` 接线。
实现要求见 **A2.1** 卡（按来源匹配的白名单、不 import 目标模块、
在 `configure()` **之前**跑、绝不做运行时 monkeypatch）。

### F5 PostgreSQL 迁移断言过期（P1）

`tests/integration/test_postgres_stack.py` 断言 `alembic_version == "0010_business_builder_runtime"`，
实际已是 `0014_runtime_leases`。改为断言"数据库已迁移到 Alembic 自己报告的 head"，
而不是某个字面量——硬编码 head 会在每次迁移后重新过期，这正是它变陈旧的原因。

### F6 规模目标与状态表述（P2）

`persistent_engine.py` 现 1306 行，超过 B5 修正后的 ≤1200。C2/D1 之后又向引擎加了
租约与批次逻辑。**不为对齐数字再拆一刀**（B5 已论证过继续拆只会把耦合藏进新文件）；
改为在 B5 卡与终态断言中记录实测值与上浮原因，并复核 `实现状态.md` 中
"A–E 全部完成"与"A2.1 未实现"的并置表述是否会被误读。

## 8c. 工程 G：收尾与定位

### G1 清理死代码（侦察结论已确认，勿再假设）

> **状态（2026-07-28）：已完成。** `SideEffectExecutor` 与 `recovery.py`/`recover_runtime`
> 已删除，`command_idempotency_key` 保留且生产仍在用；`tests/integration/test_side_effects.py`
> 改为经 `CommandExecutor.execute_command`（真实生产路径）验证同样两条性质，
> `tests/integration/test_recovery.py`、`test_runtime_reliability.py`、
> `test_runtime_recovery_batching.py` 改为直接调 `engine.startup_recover()`。
> `GaiaAppBuilder` 按结论保留，未改动。验收命令全部通过（含 PostgreSQL 套件）。

逐个查证结果——**只有两处是真死代码**：

| 目标 | 结论 | 处置 |
| --- | --- | --- |
| `runtime/side_effects.py` 的 `SideEffectExecutor` | 生产零引用，只有 `tests/integration/test_side_effects.py` 用它。它在 `lifecycle.py` 的受校验迁移表之外另做了一套 Command 生命周期 | **删除类**。同文件的 `command_idempotency_key` **是生产在用的**（`action_plan.py`、`persistent_engine.py` 各一处），模块与该函数保留 |
| `runtime/recovery.py` 的 `recover_runtime` | 生产走 `api/app.py` 直接调 `startup_recover()`；只有三个测试文件用这个包装 | **删除**，测试改调真实路径 |
| `api/builder.py` 的 `GaiaAppBuilder` | **不是死代码**。9 处测试引用、3 个文档页；且它委托给 `RuntimeAssembler`，是门面而非第二套装配 | **保留** |

> 更正记录：早前判定 `GaiaAppBuilder` "零测试覆盖" 是**错的**——那次 grep 用了
> `| head`，10 行全被 `builder.py` 自身占满，把测试引用截断了。基于该结论开的清理任务已作废。
> 教训：用 `grep -c` 或按文件聚合计数来判断"是否有人用"，不要用会截断的 `| head`。

处置原则与 B6 一致：删除的同时把测试改指真实生产路径，保留它原本验证的性质。

### G2 定位调整：从"AI 版 Spring Boot"到"受控执行与审计"

> **状态（2026-07-28）：已完成。** `README.md` 定位段、`developer-docs/index.md`、
> `developer-docs/developer-guide.md`、`developer-docs/business-guide.md` 开篇已按下述改法
> 重写，包含"不保证"清单（不构成合规认证、不替代企业 IdP、组织级隔离、无跨副本 Run 并发
> 协调、导入纯净性检查是 best-effort lint）。未改动 `docs/施工图/` 下其它文档、
> `docs/architecture-review.md`、`docs/archive/enterprise-app-evaluation-report.md`。

**为什么改**：现在的定位是"面向企业 AI 应用的开发与运行框架 / 借鉴 Spring Boot 的声明式装配"。
这个说法把价值锚定在**装配便利**上——而装配恰恰是 AI 代码生成让它变廉价的那部分，
也会立刻招来"那为什么不直接用 LangGraph / Temporal"。

代码实际投入最重、且最难被替代的地方是另一组东西：不可绕过的写入边界（`safety.py`）、
唯一权威的状态迁移表（`lifecycle.py`）、写入恢复的三种策略分类、可验证的版本证据
（指纹 + 策略覆盖摘要）、认证身份贯穿与跨组织隔离、租约化的恢复。
**这些的价值不是省代码，是让"控制真的生效"并且**可被证明**。**

**改法**：定位改为"AI 工作流的受控执行与审计运行时"。声明式装配降级为**实现手段**
而非卖点——它服务于"配置里看到的等于实际跑的"这个可审计性质，不是服务于少写代码。

**要改的表述**：`README.md` 的定位段；`developer-docs/index.md`、`developer-guide.md`、
`business-guide.md` 的开篇。**不要改** `docs/施工图/` 下的历史设计文档与评审报告——
那些是当时的记录，改动会伪造历史。

**不得夸大**：不要宣称通过任何合规认证，不要暗示框架能替代企业 IdP 或审计系统。
口吻对齐 09 号文档：明确说出哪些由 Gaia 保证、哪些依赖部署方与 IdP。

## 8d. 工程 H：可用性缺口（实机运行发现）

把应用真正跑起来后暴露的问题。三项都不是"演示不好看"，是产品本身缺东西。

### H0 证据视图对审计记录说了假话（P0，先修）

同一个 Run，状态轨迹显示 `create_human_gate` → `human_gate_approved`，
而"谁批准的"一栏写着"这个 Run 没有触发过人工确认"。

根因：面板只从 `run.pending_gate_id` 与 `action_plan.actions[].gate_id` 找 gate，
而**审批完成后 `pending_gate_id` 被清空**。于是每一个已完成的受控写入 Run——
恰恰是审计最需要看的那一类——都被写成"没有人工确认"。

这比字段缺失严重：不是没显示证据，是**伪造了"控制不存在"的证据**。
这个视图存在的全部理由就是"伪造的控制证据比没有控制更糟"，它自己犯了同一个错。

数据可达，无需改后端：`/v1/diagnostics/runs/{id}/bundle` 有 `human_gates[].gate_id`，
`/v1/human-gates/{id}` 有 `decided_by`。

**必须区分三态，不得合并**：
1. 找到并已决策 → 显示审批人（并注明来自服务端认证身份）；
2. 事件显示有 gate 活动但记录取不到 → 说"记录未能加载"，**不得**说没有 gate；
3. 完全没有 gate 活动 → "没有触发过人工确认"。
第 2 态被折叠进第 3 态，正是这个 bug。判断"有无 gate 活动"要用**事件流**
（`create_human_gate` / `human_gate_approved`），不要用会消失的 `pending_gate_id`。

### H1 缺少列出 Run 的接口

全部 GET 端点里没有任何一个能列出 Run：`actuator/runtime` 只给聚合计数，
`/v1/runs/{run_id}` 要求已知 UUID。**一个审计运行时无法回答"给我看最近的运行"。**

新增 `GET /v1/runs`，要求：

- **按组织隔离**，复用 F1 的 `authorized_run` 同一套判定：认证身份只能看到本组织的 Run。
  这条不是附加要求——列表接口是最容易一次性泄露全量数据的地方。
- 分页（`limit`/`cursor` 或 `offset`，与仓库既有风格一致），有上限，不允许无界返回。
- 可按 `status` / `scenario_id` 过滤。
- 公共契约变更 → `make contracts` 并提交 openapi。
- 测试必须含**跨组织不可见**用例。

### H2 Console 可浏览的运行列表

有了 H1 之后，"运行"页给出可点击的最近运行列表，点进去直接落在证据页签。
当前必须手工粘贴 UUID 才能看到任何东西——**这是心智负担的根源，不是审美问题**。

### H3 `make demo`：一条命令

当前要看到东西需要：起 API → 发现数据库过期 → 迁移 → curl 建 Run → curl 审批 →
起 Console → 粘贴 UUID。**这不是演示，这是一份操作手册。**

`make demo` 要做到：使用独立的干净数据库（不污染 `var/gaia.db`）、自动迁移、
预置若干有代表性的 Run（成功的受控写入、被策略拒绝的、被拒工具的）、
同时起 API 与 Console、最后只打印一个 URL 和一句"打开它，点任意一条运行"。

失败时要给出可执行的下一步，不能只抛 traceback——参见 A7 对
`SCENARIO_MODULE_NOT_FOUND` 操作建议的处理。

## 9. 风险与回退

- **A4 的组件实例类型假设**（MODEL 组件即 ModelProvider）若侦察证伪，
  停下来在任务卡上记录实际类型并调整 factory 取用方式，不要强转。
- **A2.1 的 AST 静态检查只能发现明确模式，不是安全隔离**：它按已知来源
  匹配顶层调用，绕过方式很多（动态 import、间接调用、第三方库内部 I/O）。
  文档与错误提示中不得把它表述为隔离或安全边界。
  **且不得以"覆盖不全"为由把它扩大为运行时 monkeypatch**——该方案已在
  A2.1 中明确否决，理由见该节。需要更强探测时走独立子进程 probe。
- **D1 的批次循环有卡死风险**：若某条目每次都恢复失败又留在待处理集合中，
  朴素的 while 循环会无限重试并阻塞应用启动。必须实现任务卡要求的
  "集合未缩小即退出"的终止条件，并为它写一个用例。
- **B1 迁移表**可能暴露测试未覆盖的隐式迁移路径；处理原则是"补表并注释
  场景"，绝不放宽为全通过。若 `make test-services` 暴露 PostgreSQL 特有
  路径差异，同样处理。
- 任何任务若发现必须违反 §0.2 禁止事项才能完成，**立即停止该任务**，
  在 `docs/施工图/实现状态.md` 记录阻塞原因，跳到下一个无依赖任务。
