# Changelog

All notable user-visible Gaia changes are recorded here.

## Unreleased

- Publish the verified MkDocs developer site to GitHub Pages after changes reach `main`, using a
  dedicated artifact and least-privilege deployment job; expose the canonical documentation and
  repository URLs in MkDocs while keeping pull-request workflows read-only.

- Align the developer documentation with Gaia's current runtime and deployment profiles: document
  the distinct ports and ownership of `make demo`, daily development, `dev-full`, Compose
  acceptance, and Helm production; make every Temporal-backed local startup sequence complete;
  distinguish Temporal Query and Visibility from Gaia's audit projection; and clarify that the
  external HR Showcase is an optional enhancement to the core demo.

- Expand the Guardrails AI adapter from custom local validators to the mainstream
  application-managed Hub contract: explicitly configured validators now receive static,
  run-scoped, or dynamically produced metadata; synchronous validation is moved off the async
  execution loop; asynchronous validation is awaited; and structured validated output is returned
  to Gaia as deterministic JSON. Gaia still does not discover or install Hub packages, and
  validator-owned model or remote calls remain outside Gaia Model Gateway evidence and budgets.

- Keep Temporal mandatory for customer production while renaming the development provider to `in_process` and removing the duplicate `topology` application setting; physical replicas and scheduling now remain solely deployment concerns. Replace the ambiguous `gaia.sdk` namespace with top-level `gaia` application-authoring exports and implementation-free `gaia.spi` extension contracts, moving concrete API-key authentication and in-process event publishing into `gaia.integrations`.

- Fix real-model HR onboarding plans so every proposed permission carries the same explicit fields the least-privilege policy verifies, and separate business explanations from paired technical identifiers in the demo evidence view.

- Unify the HR showcase and Console demo into one guided journey: an HR action now links directly to the same Run in the Gaia Control Center, the Console reads the HR application's runtime during `make demo`, and both surfaces share business-first navigation and evidence-oriented visual hierarchy.

- Replace proxy-sensitive `*.gaia.localhost` links with canonical loopback paths and ports, make `/docs/` and `/hr/` real gateway routes, correctly inject the dev gateway API key into Console requests, preserve `/hr/` in showcase deep links, and proxy the HR demo's `/demo/*` and `/v1/*` API calls.

- Add an external HTTP cited-retrieval provider and place demo evidence beside the selected scenario instead of on a separate page.

- Explain the active Temporal execution path and RAG integration state before the raw effective configuration.

- Show natural-language business scenario names on demo cards while retaining internal scenario IDs for diagnostics.

- Decoupled managed and external deployment dependencies, added a
  development-only single-port gateway for Console, demo, docs, Temporal UI,
  and Langfuse, and made production Helm default to API/Worker workloads with
  no Gaia-owned Console, demo, or Nginx ingress.
- Moved development Console API authentication to the unified gateway so the
  static Console remains usable without an internal Nginx dependency cycle.
- Reorganized effective configuration around Gaia's current application,
  execution, intelligence, infrastructure, and observability boundaries
  instead of leaving newer settings in an outdated "other" category.
- **Keep the Console usable on narrow screens:** the mobile header now places
  brand and help actions above one compact, horizontally scrollable navigation
  row. Application identity, profile health, onboarding actions, and page
  content wrap within the viewport instead of producing a tall navigation wall
  or horizontal overflow.

- **Run the complete production-like topology inside Kubernetes:** the OrbStack
  profile now deploys pinned upstream Temporal and Langfuse charts alongside
  Gaia, with PostgreSQL, Valkey, ClickHouse, MinIO, migration hooks, and
  cluster-DNS-only connections. Its acceptance script executes the HR scenario
  with DeepSeek and verifies the same Run in Gaia, Temporal, and Langfuse.
  Platform services can bootstrap before a model credential exists; the Gaia
  release and live-model verification resume when the credential is supplied.
  `GAIA_PROFILE` scopes all Kubernetes namespaces, releases, Secrets, and
  service DNS so multiple profiles do not share runtime state.

- **Add a production-shaped `dev-full` profile:** one local Compose stack now
- Added a production-like Helm chart for Kubernetes with migration and Temporal bootstrap hooks, replicated API and Worker workloads, Console routing, and configurable Ingress, HPA, PDB, and NetworkPolicy.
  connects Gaia and the HR reference application to PostgreSQL, Redis,
  Temporal, Langfuse and DeepSeek. The Console is routed to the HR API, while
  sandbox execution and approval-required writes preserve the control boundary.
  OpenAI-compatible structured calls now send the requested JSON Schema to the
  model instead of relying on JSON mode alone.

- **Make the Run Console understandable on first entry:** operators now follow
  one visible path from current attention items, through recent Runs, into a
  full-width evidence workspace. Explicit “查看详情” actions replace hidden row
  clicks, while Run ID lookup and Gate approval are kept as secondary tools.

- **Add a developer-facing observability workspace:** the Console now groups
  navigation into “运行与诊断” and “构建与治理”, and adds a dedicated page for
  Runtime signals, Gaia evidence coverage, component health, OpenTelemetry
  export state and optional Langfuse configuration. The page distinguishes
  recorded facts from configured integrations instead of implying connectivity.

- **Remove the business-builder positioning from the framework docs:** Gaia is
  now presented to application developers, platform engineers and delivery
  engineers rather than as a business-facing or no-code product. The leave,
  onboarding and policy examples remain as Case studies that map visible
  behavior to scenarios, policies, Human Gates, tools, Runtime and evidence.

- **Replace generated Mermaid layouts with purpose-built documentation
  canvases:** the system panorama is now a responsibility swimlane, Gaia's
  internals are a five-layer module map, and execution paths are numbered
  timelines. The diagrams use semantic HTML and responsive CSS, so labels stay
  searchable and readable without a browser renderer, CDN or oversized
  JavaScript asset.

- **Rebuild the documentation around a first-time Gaia journey:** the landing
  page now explains the product through one controlled business action before
  introducing Runtime terminology. A 20-minute demo path, role-specific
  business and developer guides, a responsibility-based system panorama, and
  a guided `function_task` example now form one route from first contact to
  implementation. A documentation contract test keeps that route connected to
  the real example and preserves the key system boundaries.

- **Remove the hand-written TypeScript client and Java/Spring sample client:**
  they duplicated the OpenAPI contract without adding a stable product surface.
  Cross-language callers should generate types from `specs/openapi.json` and use
  their platform HTTP client; the integration guide now calls out the required
  idempotency and SSE behavior that generated schemas do not explain.

- **Reorder the 运行 page around what someone came to do:** it was laid out by
  where the data came from, so the Runs the page is named after sat third,
  below a ten-field capacity table that reads `0` or `-` on any small
  deployment and a six-column "需要处理" table whose only row said there was
  nothing to handle. Capacity now folds away behind one line, an empty queue is
  a sentence instead of a table, and the Run list comes first.

  The approval controls no longer enable on a non-empty text box. 批准 / 拒绝
  appear only after the gate has been fetched and shown to be pending, next to
  what it is asking for -- previously an operator could approve a high-risk
  write by typing an id, without ever seeing the write, who requested it, or
  whether it had already been decided.

- **Make the run tables readable, and split the Console up:** a run id rendered
  in full wrapped across three lines and filled its column with hex nobody
  reads. Tables now show a shortened id with the full value on hover, and wide
  tables scroll inside themselves so the page body never scrolls sideways --
  checked at 375px and 1280px. The 运行 page moved out of `Console.tsx` into
  `RunsView.tsx`, taking `Console.tsx` from 2773 to 1783 lines, and the shared
  `Identifier` / `message` helpers now have one definition each instead of a
  copy per page.

- **Stop the operations view reporting a working control as a fault:** it led
  with 成功率 and queued every `blocked` Run under 需要处理 as a 运行错误, so
  three demo Runs -- two of them correctly refused, one by an approver and one
  by policy -- read as "成功率 33.3%" with two errors waiting for someone. That
  is the opposite of what happened, on the landing page of a project whose
  whole claim is that its evidence is honest.

  The headline is now four counts: 已完成, 被控制拦下, 待人工确认, 失败 --
  where 失败 counts only Runs that actually broke. A refusal is neither a
  success nor a failure and is reported as itself. 需要处理 lists only work an
  operator can act on; a Run whose write outcome is genuinely unknown
  (`SIDE_EFFECT_UNKNOWN`) still appears, because that one does need a human.

  Which terminal states count as a refusal comes from the error catalog's
  `ErrorCategory`, not from a list of codes in the view -- a second list would
  drift from the catalog the first time a code was added, and the drift would
  surface as this view quietly misclassifying it. Latency percentiles moved to
  the capacity table; the headline answers what happened to these Runs, and a
  percentile is not an answer to that.

- **Run the HR reference application from `make demo`, and stop showing a demo
  audience the project-init wizard:** the three HR scenarios existed in two
  places that both linked to port 4173 -- `developer-docs/showcase.md` and the
  Console's 快速开始 cards -- while 4173 is the Dev Console's own dev port and
  nothing in the repo ever started that application. `make demo` now starts its
  backend, its Temporal Worker and its frontend alongside everything else, so
  those links resolve; the Console's 演示 page offers the three scenarios
  directly. Like docs, it is best-effort: if it cannot start, the demo still
  comes up and the cards say 演示未启动 rather than failing when clicked.

  The showcase runs on its own Temporal task queue. Sharing the default
  `gaia-runtime` would let Temporal hand controlled-task work to a Worker with
  none of those scenarios registered.

  快速开始 is hidden in demo mode. Its 应用模板 action writes into
  `GAIA_PROJECT_ROOT`, which `make demo` points at the Gaia repository, so a
  viewer clicking it modified the presenter's working tree; opening the bare
  Console URL used to land there. Demo mode now lands on `#demo`. Under
  `gaia dev` / `make dev-console` nothing changes.

  Docs gained 先跑起来看一遍, the page that was missing entirely: what
  `make demo` shows and what each screen proves. The three execution chains are
  now described in `showcase.md` alone instead of being restated in `demo.md`.

- **Give a Run's evidence a page of its own, and make it readable:** 看证据
  used to hand the Run to the 运行 dashboard, so the answer sat below a success
  rate, a capacity table and a work queue -- an operator's view answering an
  auditor's question. Evidence now opens at `#evidence/<run_id>` with nothing
  above it. The page leads with what actually happened in plain language,
  derived from the Run's own record (a stage that cannot be resolved produces
  no sentence rather than a plausible one), then who approved it, what was
  refused, which policy version applied, and the state trail. The trail shows
  the steps where a control acted, labelled in Chinese with the raw runtime
  step name still on screen for anyone checking against the event stream; the
  rest are one click away. The six content-fingerprint rows collapse into the
  conclusion they were all restating.

  The trail also no longer claims every state write is validated by
  `src/gaia/runtime/lifecycle.py`. That module was deleted when Temporal took
  over execution -- the evidence view was vouching for a control that no longer
  existed, which is the defect it exists to prevent, pointed the other way.

- **Add a demo landing page (`#demo`) so `make demo` explains itself:** before
  this, `make demo` opened straight onto the operator dashboard, which said
  nothing about what Gaia is or what its three seeded Runs prove. `make demo`
  now opens `#demo` -- a one-sentence explanation of Gaia plus one card per
  seeded Run, each stating the scenario, the outcome (已完成 / 被人工拒绝 /
  被策略拒绝), and which control acted, with a "看证据" button that opens that
  Run's existing 证据 tab on the 运行 page (no evidence rendering was
  duplicated). Card data comes from `GET /v1/runs`; a label is only ever shown
  when it can be backed by that Run's actual status, error code, or decided
  HumanGate -- never guessed. `scripts/demo.py`'s closing banner now points at
  `#demo` instead of `#runs`.

  This also closes a real gap the demo exposed: the Run approved by a human
  and then completed had no way to name its approver once finished, because
  nothing on `RunSnapshot` survives completion for that scenario shape and no
  endpoint exposed the durable gate history that does. `GET
  /v1/runs/{run_id}/human-gates` now serves it (org-isolated the same way as
  every other `/v1/runs/{run_id}/...` route -- a Run in another organization
  is 404, not 403), backed by a new `AuditProjection.gates_for_run` on both
  the real store and its in-memory test double. The 运行 page's "人工确认"
  column now also uses this to show "已通过 · demo-approver" instead of
  "未记录" for a Run this can actually verify -- it still says "未记录" whenever
  the record cannot be confirmed, never a guess.

- **Fix every documentation link in the Console being dead during `make
  demo`:** the sidebar's "Gaia 文档" entry, the developer-docs deep link on
  the Prompt page, and the three showcase example cards all pointed at ports
  `make demo` never started, so the first external link a demo audience
  clicked was a connection-refused error. `make demo` now also starts
  `mkdocs serve` on the same port `make dev-docs` uses, and tells the Console
  the truth about what actually came up: a link is only ever rendered when
  its target is confirmed running; otherwise it appears visibly disabled and
  labeled "演示未启动" rather than as an ordinary link that errors when
  clicked. The showcase app is still never started by `make demo`, so its
  three example cards are always shown this way. Docs failing to start (for
  example, `mkdocs` missing) no longer aborts the demo -- it prints a
  readable warning and continues without a docs link.

- **Stop Temporal namespace access from being approver authority:** a Workflow
  cannot authenticate anyone, so its `decide` Update believed the `roles` in its
  own payload -- and anyone who could reach the namespace could skip Gaia's API
  and send `roles=["approver"]`. Granting approval now happens only through
  `AuditProjection.record_decision` on the authenticated API path; the
  projection accepts `rejected` and `expired` from the Workflow (both withhold
  authority) but will never let it produce an `approved`. `execute_command`
  checks that record before performing a gated write and refuses with
  `GATE_DECISION_UNVERIFIED` otherwise. The `run_scenario` Activity also
  re-runs `validate_run_admission` against the server-side policy, so a
  Workflow started straight against Temporal cannot skip environment-mode and
  role admission. Forging a version bundle and cancelling a Run remain possible
  from the namespace and are now documented as such in
  `docs/工程纪实-决策与缺陷.md`.

- **Stop Workflow changes from stranding in-flight Runs:** Temporal replays a
  Run's recorded history against current code, so editing
  `GaiaRuntimeWorkflow` could leave Runs unable to advance -- including Runs
  parked on a HumanGate, whose default TTL is a day, which makes "in flight
  during a rollout" the normal case. Two things now prevent that.
  `tests/integration/test_workflow_replay.py` replays recorded histories of
  every Workflow path (read-only, human gate, LangGraph continuation, audit
  write) against the current code and names the path that broke; `make
  capture-histories` re-records them. And setting
  `runtime.execution.deployment_name` with `build_id` starts Workers under
  pinned deployment versioning, so a rollout moves only new Runs to new code.
  Setting one without the other is rejected at config load rather than
  silently leaving Workers unpinned.

- **Keep audit evidence after Temporal forgets the Run:** migration
  `0016_audit_projection` adds Gaia-owned `audit_runs`, `audit_run_events`, and
  `audit_human_gates` tables, written by the new `gaia.runtime.record_audit`
  Activity at every point a Run's evidence changes. Making Temporal the
  execution source of truth had also made Workflow History the *only* record of
  what was approved, denied, and executed -- and namespace retention (7 days in
  Gaia's own production-like stack) deletes it. `inspect`, `events_after`, and
  `get_gate` now fall back to this projection when Temporal reports the
  Workflow gone, and `GET /v1/runs` reads it directly: listing no longer costs
  one Workflow Query per row, no longer requires a live Worker, and no longer
  returns nothing for Runs past the retention window. A Run whose evidence
  cannot be recorded does not reach a terminal state. Workflows now also retain
  every HumanGate they opened rather than only the current one.

- **Add a local production-like fault acceptance stack:** Docker Compose now
  runs two Gaia APIs, two application Workers, Temporal Server with dedicated
  PostgreSQL, Gaia PostgreSQL, the full self-hosted Langfuse v3 dependency
  set, gateway, Temporal UI, and Console. `make prod-acceptance` proves a
  HumanGate survives Worker replacement, API failover remains readable,
  Temporal survives Server restart, Visibility lists the Run, and Langfuse
  exposes its trace. The controlled-task application now honors
  `GAIA_CONFIG_PATH` and wires Langfuse into both Temporal interceptors and
  model evidence.
- **Add the canonical application Worker and runnable full-stack demo:** `gaia
  worker --config ... --app module:factory` now enters the same ASGI lifespan
  as the API and registers that composition's `TemporalRuntimeEngine` on its
  configured task queue. `make demo` starts a disposable Temporal development
  server, the Worker, API, and Console, and polls Workflow projections while
  seeding approval, rejection, and policy-refusal evidence.
- **Remove Gaia's executable SQL Runtime:** deleted
  `PersistentRuntimeEngine`, its Command/Handoff coordinators, the SQL budget
  store, and the legacy test assembler. Controlled-task acceptance now runs
  ten cases against a real Temporal Server and Worker, and Workflow History
  preserves business trace actor/source/rule attribution.
- **Remove the SQL execution ledger:** migration
  `0015_remove_sql_runtime` detaches observation records from the retired
  `runs` foreign key and drops Run, event, budget, HumanGate, Command,
  idempotency, and lease tables. Observation `run_id` values are now external
  Temporal correlation identifiers.
- **Move Run budgets into Temporal execution state:** production assembly now
  uses Activity-local budget counters instead of `SqlAlchemyRunBudgetStore`.
  Reservations heartbeat before model/tool work, successful Activities return
  counters into Workflow History, handoffs and continuations carry them
  forward, and Command Activities reserve their step in the Workflow.
- **Stop treating PostgreSQL as a Runtime backend:** removed the external
  PostgreSQL test that created a Run through `PersistentRuntimeEngine`.
  PostgreSQL integration coverage now stays within its legitimate Prompt,
  Outbox, RAG, checkpoint, migration, and observability storage boundaries;
  durable Run execution is proven only against Temporal.
- **Pin Prompt releases with Temporal Workflow identity:** replaced the SQL
  idempotency test with a real Temporal Server + Worker test. New Workflow IDs
  resolve the current Prompt release, while retrying the same organization and
  idempotency key returns the original Workflow snapshot and pinned version.
- **Boot examples and generated apps on Temporal:** the `function_task`
  reference app and `gaia init` basic/approval projects now start their real
  declarative component graph and assert `TemporalRuntimeEngine` without
  monkeypatching SQL execution. Their tests own composition and generated-file
  contracts; Workflow behavior remains in the real Temporal acceptance suite.
- **Make Starter contracts assert Temporal assembly:** model and scenario
  Starter tests no longer monkeypatch production runtime creation to SQL.
  Declarative component graphs now prove they discover real providers and
  assemble `TemporalRuntimeEngine`; explicit dependency precedence is checked
  at application lifespan without executing a second Runtime.
- **Collapse Function Scenario API coverage onto Temporal assembly:** replaced
  the legacy Runtime monkeypatch and mixed HTTP/Runner suite with focused
  contracts proving `ApiDependencies.from_scenarios` builds
  `TemporalRuntimeEngine`, rejects duplicate IDs at assembly, and resolves
  Prompt releases before Workflow start. Guardrail, correction, and read-tool
  behavior remain covered by their direct unit suites and real Temporal E2E.
- **Test resource ownership against Temporal projections:** Run and HumanGate
  authorization tests now use preloaded Runtime SPI Query projections and
  captured cancel/decision boundaries. Cross-organization and forged-role
  requests prove they never reach Temporal Signal/Update calls, without
  creating SQL Runs, Commands, or Gates.
- **Decouple authentication tests from workflow execution:** API-key, custom
  AuthnProvider, and OIDC wiring tests now capture the authenticated
  `RunRequest` at the Temporal Runtime SPI boundary. They no longer execute a
  Scenario through `PersistentRuntimeEngine`; real execution remains covered
  by Temporal Server + Worker acceptance.
- **Make Run listing a Temporal Visibility boundary:** removed the legacy SQL
  engine's pagination, ordering, filtering, and cursor tests. Runtime coverage
  now proves organization/status/scenario filters and page size are sent to
  Temporal Visibility, while HTTP coverage only verifies authenticated scope
  and opaque cursor forwarding through the Runtime SPI.
- **Move Handoff acceptance to Temporal:** replaced the legacy SQL-runtime
  Handoff integration test with a real Temporal Server + Worker workflow that
  proves two agent handoffs, shared state, HumanGate approval, and Command
  Activity execution in one Workflow History. The Activity outcome boundary now
  accepts a Handoff as a valid durable intermediate result. Removed duplicate legacy
  Function Scenario and continuation tests already covered by Temporal
  Activity and Worker-restart acceptance.
- **Retire SQL-runtime tests superseded by Temporal acceptance:** removed the
  controlled-task SQL approval smoke test, the test that invoked private
  `CommandExecutor` methods, and legacy Run/Event table-constraint tests.
  Approval-before-write, exactly-once observed execution, event durability, and
  Worker restart recovery are now proven by the real Temporal Server/Worker
  integration suite instead of assertions against the engine being removed.
- **Delete orphaned SQL execution repositories:** removed
  `gaia.persistence.repositories` after all Run, Event, Gate, Idempotency, and
  Command repository classes became unreferenced. This also removes the last
  repository-level `list_recoverable()` API, preventing Gaia code from
  reintroducing a Command recovery scanner beside Temporal.
- **Make Actuator runtime observability a single SPI projection:** removed the
  SQL-backed `RuntimeObservabilityService` and the concrete-Runtime branch in
  `/actuator/runtime`. The sole service now reads `RuntimeEngine.list_runs`,
  including Temporal Visibility in production; Gaia no longer counts legacy
  Run, Gate, Command, or Outbox rows as execution truth or exposes database-pool
  contention as a Runtime metric. Applications with no Runtime return an empty
  projection marked `database.backend=unconfigured` instead of falling back to
  the operational SQL store.
- **Project diagnostic bundles from the active Runtime:** `DiagnosticExporter`
  now reads Run snapshots, events, and HumanGates through `RuntimeEngine`
  instead of querying Gaia's legacy Run/Command SQL tables. Bundle schema 2.0
  removes `side_effect_commands` and points operators to Temporal Workflow
  History for Command evidence, while preserving pseudonymized Run and approval
  evidence.
- **Route acceptance Replay through the Runtime SPI:** `ReplayRunner` now
  receives a standard `RuntimeEngine` factory, so production replays start
  Temporal Workflows instead of requiring a fixture object with
  `create_runtime()`. The legacy-only `ReplayRuntime` protocols and
  `side_effect_success_count` assertion have been removed; replay evidence is
  derived from Run snapshots and Workflow events.
- **Move the controlled-task reference app onto Temporal:** its public ASGI
  composition root now constructs `TemporalRuntimeEngine` with the real client
  backend, and `ControlledTaskComposition.create_runtime()` has been deleted.
  SQL-runtime behavior that has not yet migrated is assembled explicitly from
  `tests.integration.controlled_task_legacy_app`, so the production example no
  longer doubles as a hidden legacy provider.
- **Remove external Runtime state mutation:** deleted `RuntimeEngine.transition`,
  its Temporal client envelope, the Workflow `transition` Signal, and the legacy
  SQL test hook. Workflow status now advances only through Gaia's deterministic
  Workflow logic, Activities, HumanGate Update, or the explicit cancel Signal;
  callers cannot push arbitrary durable states.
- **Remove Gaia's duplicate Command query contract:** `RuntimeEngine.get_command`
  and both SQL/Temporal adapter stubs have been deleted. Command execution truth
  remains in Temporal Workflow History and Langfuse traces instead of being
  projected as a second Gaia-owned Command API.
- **Keep the Scenario test harness above the durable execution layer:**
  `ScenarioTestHarness` now evaluates one logical Scenario step and records
  read/model evidence plus write proposals without creating SQLite state or a
  `PersistentRuntimeEngine`. Its duplicate `execute()`/approval path has been
  removed; durable HumanGate and Command execution are verified through the real
  Temporal Worker integration suite.
- **Decouple the HTTP Runtime boundary from the retired SQL engine:** list
  pagination limits and `InvalidRunCursor` now belong to the `RuntimeEngine`
  contract. FastAPI no longer imports `persistent_engine.py`, and Temporal
  Visibility rejects malformed cursors through the same public error contract.
- **Remove duplicate Runtime compatibility entry points:** deleted the top-level
  `runtime.provider` setting and `effective_runtime_provider()` fallback so
  `runtime.execution` is now the only declarative execution configuration surface.
  The public `gaia.runtime.engine.RuntimeEngine` name now denotes the Runtime
  protocol instead of constructing `PersistentRuntimeEngine`; legacy SQL runtime
  tests import that implementation explicitly.
- **Make Temporal the sole declarative execution provider:** removed `persistent`
  from `RuntimeExecutionSettings` and deleted the Persistent branch from
  `RuntimeAssembler`. SQL Runtime regression coverage now opts in through the
  explicitly test-only `gaia.testing.legacy_runtime` seam; application configuration,
  Starters, generated projects, and examples can only assemble Temporal.
- **Add a real Temporal execution acceptance baseline:** an opt-in integration test now
  launches the Temporal SDK test Server and a real Worker, starts Gaia's production
  Workflow through `TemporalClientBackend`, executes the registered Scenario Activity,
  and verifies the terminal `RunSnapshot` without any fake backend or SQL Runtime.
  The test exposed and fixed Worker sandbox bootstrap: Gaia application modules are
  now registered as Temporal passthrough imports, while Workflow execution remains
  sandboxed for deterministic-call enforcement. A second real Workflow verifies
  HumanGate waiting, approval through a Temporal Update, and one Command Activity
  execution; it also fixed the missing approval comment in the durable Update payload.
  A third test stops the Worker at the HumanGate, starts a fresh Worker, replays
  Workflow History, executes the approved Command, and restores its result into the
  next LangGraph state transition without a LangGraph checkpointer.
- **Remove Gaia-owned startup recovery and replay:** `startup_recover` has been
  removed from the Runtime SPI, API lifespan, Temporal adapter, and legacy persistent
  provider. The SQL recovery LeaseStore, batched Run scans, handoff/continuation
  recovery, and Command reconcile/replay loop have also been removed. An inconclusive
  live legacy Command now enters `needs_attention` instead of being replayed by Gaia.
  Temporal Workflow History, Activity Retry, task queues, and Worker replay are the
  only production recovery mechanisms. Readiness no longer reports a misleading
  `startup_recovery_runs` count.

- **Retire Gaia's ActionPlan scheduler in favor of LangGraph:** the public
  `ScenarioResponse.propose_plan` and `RuntimeOutcome.action_plan` paths have been
  removed, together with `ActionPlanManager`, its startup-recovery phase, and
  Command-result plan advancement. Multi-step applications now route one logical step
  at a time through `LangGraphScenarioRunner`; Temporal durably executes each proposed
  Command before resuming the graph. Existing `action_plan_json` database values remain
  readable as historical snapshots but Gaia no longer schedules or recovers them.

- **Move multi-step logical routing to LangGraph without a second durable
  scheduler:** `LangGraphScenarioRunner` now invokes one graph step per Temporal
  Scenario Activity. When a graph proposes a write, its JSON-safe state is carried in
  the existing Temporal continuation and resumed with the durable Command result.
  LangGraph chooses the next logical step; Temporal owns Workflow History, HumanGate
  waits, retries, and Command execution. The adapter rejects ActionPlan output and
  does not use a LangGraph checkpointer, preventing Gaia DAG scheduling and duplicate
  persistence from reappearing under a different name.

- **Make Temporal the production-default execution provider:** declarative Gaia
  applications initially defaulted `runtime.execution.provider` to `temporal`.
  This migration checkpoint has now been superseded by the sole-provider change above.

- **Map safe model evidence into Langfuse generations:** Gaia's existing
  `OpenTelemetryModelInvocationSink` now marks model spans as Langfuse generations and
  emits model identity, standard GenAI input/output/total token attributes, USD cost
  when supplied by the provider, Prompt version, and filterable Run/Scenario metadata.
  Prompt and response bodies remain excluded by default; the waterfall shows durable
  call structure, timing, versions, usage, and cost without silently exporting customer
  content. Langfuse environment values now follow the backend's documented naming
  constraints.

- **Resume LangGraph/Scenario logic through Temporal Activities:** agent handoffs now
  re-enter the application runner as subsequent Scenario Activities, and a successful
  single write can pass its result into the runner's declared continuation handler.
  Temporal retains the durable Activity chain, retry history, and HumanGate wait while
  Gaia keeps policy enforcement. Multi-action ActionPlan scheduling remains deliberately
  unmapped rather than recreating a Gaia DAG scheduler inside the Workflow.

- **Project Temporal runs into Actuator without dual-writing Gaia run rows:** Gaia now
  starts Workflows with organization, scenario, and run-status Search Attributes and
  updates the status attribute from Workflow history. Temporal `list_runs` reads
  Visibility pages and queries the owning Workflows for public snapshots.
  `/actuator/runtime` selects this read-only projection when Temporal is the configured
  provider; runtime issues include the correlated Langfuse/OTel trace ID. Persistent
  applications retain the existing database-backed summary.

- **Add declarative Langfuse trace export without a Gaia trace store:** selecting
  `observability.provider=langfuse` now creates an isolated OpenTelemetry OTLP/HTTP
  exporter using redacted `SecretRef` credentials, injects Temporal's official tracing
  interceptor into both the runtime client and Worker, and fans existing safe model
  invocation spans into the same tracer. Scenario and command Activities attach Gaia
  run/scenario correlation attributes and return the actual 32-character OTel trace ID
  to the Run snapshot. Prompt-body capture and Langfuse-backed Actuator aggregation
  remain explicitly incomplete.

- **Run the first real Temporal-backed runtime slice:** selecting
  `runtime.execution.provider=temporal` now wires a lazy Temporal Client backend and a
  registered `gaia.runtime` Workflow instead of an always-failing placeholder. Gaia
  still performs scenario admission and version resolution before Workflow start;
  Temporal owns the durable run ID, initial snapshot, event query, transition Signal,
  cancellation Signal, and replay recovery for this slice. Read-only terminal
  Scenario/LangGraph runners now execute as a retried Temporal Activity and return
  `RuntimeOutcome` data to the Workflow. Single write proposals now become durable
  HumanGates inside Workflow history; `get_gate` uses a Query and `decide` uses a
  synchronous Workflow Update with rejection, approval, expiry, and repeated-decision
  state retained by Temporal. Approved and policy-authorized writes now execute as
  Temporal Activities with deterministic command idempotency keys; Temporal owns retry
  attempts while Gaia retains policy, input/output guardrails, and recovery-strategy
  declarations. This intentionally does not add a second Gaia Command store or recovery
  poller. Listing, Langfuse correlation, and projection parity remain incomplete.

- **Add Temporal migration execution wiring foundations:** `runtime.execution` now carries
  explicit Temporal transport controls (`server_address`, `tls_enabled`) and exposes a
  new `src/gaia/runtime/temporal_worker.py` bootstrap profile API for the migration
  first replacement pass (`TemporalWorkerProfile`, `build_temporal_worker_profile`,
  `build_temporal_entrypoint_kwargs`, and `ensure_temporal_runtime_available`).
  `TemporalRuntimePlan` now includes server/host/port/tls context so migration errors are
  materially actionable while runtime execution is still on the safe adapter path.

- **Refactor execution runtime boundary for Temporal migration:** added a `RuntimeEngine`
  protocol in `src/gaia/runtime/contracts.py`, switched API/runtime assembly to
  depend on the protocol, added `runtime.provider` (`gaia`/`temporal`) in
  `RuntimeSettings`, and wired a migration-time `TemporalRuntimeEngine` branch in
  `RuntimeAssembler` so the current default behavior remains unchanged while the
  adapter path is introduced.

- **Added migration-forward execution switch and Temporal adapter scaffold metadata (`runtime.execution`):**
  `RuntimeSettings` now supports `runtime.execution` with dedicated execution
  controls (`provider: persistent|temporal`, `namespace`, `task_queue`, timeout and
  concurrency), `RuntimeSettings.effective_runtime_provider()` now resolves legacy
  `runtime.provider` together with the new `runtime.execution.provider`, and
  `RuntimeAssembler` now selects the Temporal branch via this resolution path.
  `TemporalRuntimeEngine` now records a typed execution plan snapshot and emits
  deterministic migration-ready diagnostics that expose why Temporal execution is not
  yet fully wired, preventing silent behavior drift during cutover. Test coverage now
  includes execution-provider override behavior and dual-path engine selection.

- **Started Temporal migration first jump for runtime replacement:** `TemporalRuntimeEngine`
  now defines deterministic `build_*_envelope` helpers for all public runtime
  operations (`create`, `decide`, `cancel`, `transition`, `inspect`, `list_runs`,
  `events_after`, `get_gate`, `get_command`, `startup_recover`) so the first cutover
  path has explicit, structured operation contracts. New unit tests assert migration
  plan exposure, request-to-envelope mapping, and that migration failures now expose
  operation + envelope context in `TemporalRuntimeUnavailable`.

- **Added `make demo`, and a browsable run list in the Dev Console (tasks H2/H3)**:
  seeing anything working used to require starting the API, discovering the local
  database was behind, migrating it, `curl`-ing a run into existence, `curl`-ing an
  approval, starting the Console, and pasting a UUID copied out of a terminal --
  an operating manual, not a demonstration. `make demo` (`scripts/demo.py`) now takes a
  fresh clone to real evidence in one command: it migrates its own disposable SQLite
  database (`var/gaia-demo.db`, never `var/gaia.db`, so it can never disturb a
  developer's local state or inherit a stale schema), seeds a controlled write that went
  through human approval and completed, one a human approver refused, and one refused by
  policy before a human was ever involved, starts the reference API and Console on their
  own ports (8010 / 4180, alongside `make dev-api` / `make dev-console` rather than
  colliding with them), and prints exactly one URL and one sentence telling the reader
  what to click. A failure prints a concrete next step, never a bare traceback, in the
  style already established for `SCENARIO_MODULE_NOT_FOUND` (task A7). The seeding logic
  is exercised by `tests/integration/test_demo.py` (following the `make attack-demo` /
  `test_attack_demo.py` precedent) so it cannot rot the way an unrun demo would. Separately,
  the Console's 运行 view now shows a list of recent runs (scenario, status, when, and
  whether it went through human approval) above the existing by-Run-ID lookup, backed by
  H1's `GET /v1/runs`; clicking a row opens that run's detail already on 证据. The
  human-approval column deliberately never claims "no gate" when it cannot verify one --
  a run whose write went through a single `SideEffectProposal` (rather than the
  multi-step ActionPlan mechanism) carries no gate evidence left on `RunSnapshot` once it
  completes, so that case renders as "未记录" (not on record here) rather than repeating
  the affirmative-lie failure task H0 fixed in the Evidence tab, just at list scale.
  README now leads with `make demo` instead of the three-terminal manual setup.
- **Added `GET /v1/runs` to list Runs (task H1)**: previously there was no way to list
  Runs at all -- `actuator/runtime` only returns aggregate counts, and
  `GET /v1/runs/{run_id}` requires already knowing a UUID, so an audit runtime could not
  answer "show me recent runs". The new endpoint returns a `RunPage` (newest first,
  ordered by `(created_at DESC, run_id DESC)`) with `status` / `scenario_id` filters and
  cursor pagination (`limit`, default 50, max 200; a `limit` above 200 is rejected with
  `422`, matching how `actuator.py` already enforces `window_hours` /
  `stale_after_seconds`). A cursor was chosen over an `offset` because an audit view that
  silently drops or repeats rows when new Runs arrive mid-page is a correctness bug, not
  a cosmetic one. **Organisation scoping follows F1's `authorized_run` boundary exactly**:
  when the authenticated identity carries an organisation, `PersistentRuntimeEngine
  .list_runs` filters by it in the SQL query itself (a JSON-path comparison on
  `RunRecord.user_json`, not a broad fetch filtered in Python); when `authenticate`
  returns `None` (API-key trusted-service mode), no organisation filter is applied and
  Runs are returned across every organisation -- the same trust boundary `authorized_run`
  already documents for single-Run reads, not a new hole. New contract model
  `contracts.models.RunPage`; `specs/openapi.json` regenerated. Tests in
  `tests/integration/test_run_listing.py` cover cross-organisation invisibility (asserted
  on absence, not count), limit clamping/rejection, exhaustive cursor paging with no
  duplicates or gaps, status/scenario_id filters, newest-first ordering stability, and the
  API-key trust-boundary path. Documented in `developer-docs/http-api.md`.
- **Fixed a false negative in the Evidence tab's "谁批准的" (who approved this) section**:
  it discovered HumanGate ids only from `run.pending_gate_id` and
  `action_plan.actions[].gate_id`, both of which the Runtime clears once a gate is
  decided and a run completes -- so a *completed, approved* Run, exactly the class an
  auditor opens, was reported as "这个 Run 没有触发过人工确认" (never went through human
  confirmation) even when its own event trail showed `create_human_gate` followed by
  `human_gate_approved`. That is not a missing-evidence gap; it is the view asserting a
  control did not exist when it did. The Console now also reads
  `GET /v1/diagnostics/runs/{id}/bundle`'s `human_gates[]` (best-effort: a bundle
  failure no longer blanks the rest of the panel) and treats the event stream, not the
  clearable `pending_gate_id`, as the signal for "did this run ever have gate activity".
  Three states are now distinguished and never collapsed into each other: a decided gate
  found and shown with its `decided_by`; gate activity seen in the events (or a known
  gate id that failed to load) but no record fetchable, shown as "记录无法读取" and
  explicitly not as "no gate ever existed"; and no gate activity anywhere, which is the
  only case allowed to say no human confirmation was triggered. Covered by new Playwright
  cases in `apps/web/tests/smoke.spec.ts` for all three states. Documented in
  `developer-docs/getting-started.md`.
- **Added a 证据 (Evidence) tab to the Dev Console's Run detail view, first in the tab
  list**: it renders, from endpoints the Console already calls (`GET /v1/runs/{id}`,
  `/events`, `/tool-invocations`, `/guardrail-decisions`, `GET /v1/human-gates/{id}`; no
  new backend endpoint was added) the five things that make "the config you showed me is
  the config that ran" checkable instead of asserted: which policy version governed the
  run and whether its `+ovr.<digest>` suffix shows an operator tightened it from
  `gaia.yaml` (`apply_policy_override` in `src/gaia/runtime/policy.py` can only make a
  policy stricter, and rejects a loosening override at startup); which `version_bundle`
  fields are `sha256:...` content fingerprints (`gaia.fingerprint`) versus
  hand-typed literals, shown as what they actually are rather than dressed up as
  fingerprints; the `decided_by` identity on any HumanGate the run passed through,
  labeled explicitly as the server's authenticated identity rather than a client-supplied
  field; every denied tool invocation, blocked guardrail decision, and terminal error
  code the run produced -- with an explicit "nothing was refused" statement when there
  is nothing to list, instead of an ambiguous empty region; and a compact trail of the
  run's recorded events, noting that every state write is validated against
  `src/gaia/runtime/lifecycle.py`'s transition tables. Absent fields (a missing
  `version_bundle` entry, a gate with no `decided_by`, no HumanGate at all) render as
  explicitly absent rather than as a plausible-looking placeholder -- this view exists
  specifically so fabricated evidence of a control never looks like the real thing. It
  does not label anything as verified, certified, or compliant, and does not prove the
  underlying enforcement itself was not bypassed -- only that this is what got recorded.
  Documented in `developer-docs/getting-started.md`.
- **Added `make attack-demo`, a runnable attack-and-defence regression check**:
  `scripts/attack_demo.py` executes eight previously-reproduced attacks against the
  controls `README.md` claims are unbypassable -- a forged `approver` role, cross-
  organisation Run/Gate access, an `alg=none` JWT, an RS256/HS256 key-confusion JWT, a
  loosening `policy_overrides` entry, a `deny_tools`-denied tool called directly via
  `context.tools.call(...)`, two replicas racing `startup_recover()` against one
  database, and an import-time secret resolution flagged by `gaia check` -- and prints,
  for each, what was attempted, what happened, and the exact file:line/symbol enforcing
  the outcome. Needs no Docker, network, or PostgreSQL (SQLite, the mock model, and
  locally generated RSA keys only) and exits non-zero if any defence fails to hold, so
  it doubles as a regression check rather than a demo that can silently rot. Closes with
  an explicit statement of what it does not prove (organisation-scoped authorization
  only, no cross-replica coordination of steady-state Run execution, the import-purity
  check is a lint, not a compliance claim), matching the tone of
  `docs/施工图/09-Runtime安全边界与Sandbox.md`. `README.md` now points at it from the
  定位 section.
- **Positioning correction, not a feature (task G2)**: reworded the framework's positioning
  in `README.md`'s 定位 section and the opening of `developer-docs/index.md`,
  `developer-docs/developer-guide.md`, and `developer-docs/business-guide.md`, from
  "an AI application framework with Spring-Boot-like declarative assembly" to "a controlled
  execution and audit runtime for AI workflows". No behavior changed; the previous wording
  anchored the framework's value on assembly convenience -- exactly the part AI code
  generation has made cheap -- while the parts that took the real engineering investment
  (the unbypassable write boundary, the single authoritative lifecycle table, per-strategy
  write-recovery budgets, verifiable version evidence, authenticated-identity-as-source-of-
  truth with cross-organisation isolation, lease-guarded startup recovery) went unmentioned.
  Declarative assembly is now described as the mechanism that makes "what the config says"
  equal "what actually runs", not the headline. The new text also states explicitly what is
  not guaranteed (no compliance certification, does not replace an enterprise IdP or audit
  system, organisation-scoped authorization only, no cross-replica coordination of
  steady-state Run execution, the import-purity check is a best-effort lint, not isolation),
  matching the tone already used in `docs/施工图/09-Runtime安全边界与Sandbox.md`.
- **Removed dead Command-lifecycle duplicate `SideEffectExecutor` (task G1)**:
  `gaia.runtime.side_effects.SideEffectExecutor` was an in-memory, standalone
  re-implementation of the approve -> execute -> reconcile Command lifecycle that production
  never referenced -- the real lifecycle runs through `CommandExecutor`
  (`gaia.runtime.command_execution`), validated against `lifecycle.py`'s transition table.
  Deleted the class; `command_idempotency_key` in the same module is unaffected and remains
  in production use (`action_plan.py`, `persistent_engine.py`). Repointed
  `tests/integration/test_side_effects.py` at the real production path: it now exercises
  `CommandExecutor.execute_command` through `create_controlled_task_composition()` to check
  the same two properties (a proposed-but-unapproved command cannot execute; a
  already-succeeded command is not re-executed).
- **Removed dead `recover_runtime` wrapper (task G1)**: `gaia.runtime.recovery.recover_runtime`
  was a six-line pass-through to `engine.startup_recover()` that production never called --
  `src/gaia/api/app.py` already calls `startup_recover()` directly. Deleted the module;
  repointed the three test files that used the wrapper
  (`tests/integration/test_recovery.py`, `tests/integration/test_runtime_reliability.py`,
  `tests/integration/test_runtime_recovery_batching.py`) to call `engine.startup_recover()`
  directly.
- **Fixed `make package-smoke` / `make verify` release gate (task F3)**: the smoke script
  ran `gaia check` before installing the generated project, so under declarative assembly
  `gaia check`'s import of `scenarios.modules` always failed with
  `SCENARIO_MODULE_NOT_FOUND`. `scripts/package_smoke.py` now installs the generated
  project (editable) before running `gaia check`, matching the scaffold contract `gaia
  init`'s own output and generated README already document.
- **Implemented the A2.1 Scenario-module import-purity check (task F4)**: added
  `gaia.diagnostics.import_purity` (`scan_module_purity`, `PurityFinding`, `IMPURE_CALLS`)
  and wired it into `gaia check`, run before `configure()` against every module in
  `scenarios.modules`. It never imports the target module -- it resolves the module's
  source via `importlib.util.find_spec` and `ast.parse`s it, matching only module-level
  calls that resolve, through the module's own `import`/`from ... import` aliases, to a
  fixed allowlist (`resolve_secret`, `create_engine`, `httpx.Client`/`AsyncClient`,
  `redis(.asyncio).Redis.from_url`, `open`). A call whose source cannot be resolved is
  never flagged (no bare-name matching), and calls inside function/class bodies are
  ignored (runtime, not import time). This is a best-effort lint, not an isolation or
  security boundary; it does not runtime-monkeypatch anything (that approach was
  considered and rejected -- see the module docstring for why). See
  `src/gaia/diagnostics/import_purity.py`, `tests/unit/test_import_purity.py`, and the new
  `gaia check` test in `tests/cli/test_main.py`.
- **Fixed the stale PostgreSQL migration-head assertion (task F5)**:
  `tests/integration/test_postgres_stack.py` hardcoded the Alembic head as the literal
  string `"0010_business_builder_runtime"`, which broke every time a new migration was
  added (the head is now `0014_runtime_leases`). It now asserts the database is stamped at
  whatever head Alembic itself reports from the migration scripts directory, so the
  assertion stays correct as migrations are added.
- 将 HR Showcase 从 Dev Console 日常导航收敛到 Quick Start 和 Dev Doc，并补齐入职权限、
  个性化员工政策问答和请假办理三个案例的完整执行链说明。
- **Added a built-in OIDC/JWT `AuthnProvider` for enterprise IAM integration (task F2)**:
  `gaia.integrations.oidc.JwtAuthnProvider` validates Bearer tokens issued by an external
  IdP (Keycloak, Okta, Entra ID, Ping, ...) against its published JWKS and maps claims to
  a `UserIdentity`. Gaia still does not build an identity system: token issuance, user
  lifecycle, and role administration remain the IdP's responsibility.
  - Signature verification uses a fixed, server-side algorithm allowlist restricted to
    asymmetric algorithms (`gaia.config.models.OIDC_ASYMMETRIC_ALGORITHMS`: `RS*`/`PS*`/`ES*`);
    `none` and symmetric (`HS*`) algorithms are rejected at config-validation time, and the
    token's own header `alg` never selects the verification algorithm -- this closes both
    the `alg: none` bypass and the classic RS256/HS256 key-confusion attack.
  - `iss` / `aud` / `exp` / `nbf` are validated with a configurable clock-skew leeway.
  - JWKS keys are cached in memory with a configurable TTL; a failed fetch starts a backoff
    window (reusing the last known-good keys, if any) so a JWKS outage cannot turn into a
    tight retry loop against the IdP.
  - Claim-to-identity mapping is fully configurable (`authn.claims.{subject,organization,roles}`,
    dotted paths for nested claims) so Keycloak's nested `realm_access.roles`, Entra ID's
    flat `groups`, and Okta's custom role claims are all supported without hardcoding any
    one vendor's layout; a missing or wrongly-shaped mapped claim raises
    `AuthenticationError` naming the claim.
  - Any validation failure raises `AuthenticationError` (401), matching the `AuthnProvider`
    three-outcome contract from task E3 exactly -- this provider never returns `None`,
    since a JWT that passes validation always names an end user.
  - Constructible from `gaia.yaml` (`authn.provider: oidc`, consumed by `create_app` when
    no explicit `authn=` is passed) or directly in code via `JwtAuthnProvider(...)`.
    `authn.provider` defaults to `"disabled"`; an application that configures nothing keeps
    today's `ApiKeyAuthnProvider` default byte-for-byte.
  - New `gaia-framework[oidc]` extra (`pyjwt[crypto]`), not part of the default install;
    `gaia.integrations.oidc` has no top-level dependency on `pyjwt` and imports it lazily,
    raising `CONFIG_OPTIONAL_DEPENDENCY_MISSING:oidc` if the provider is constructed
    without the extra installed (same pattern as `RedisClientStarter`).
  See `src/gaia/integrations/oidc.py`, `src/gaia/config/models.py`'s new `AuthnSettings` /
  `ClaimMappingSettings`, `developer-docs/http-api.md`'s new "内置 OIDC/JWT
  AuthnProvider：企业 IAM 对接（F2）" section, `docs/施工图/09-Runtime安全边界与Sandbox.md`
  §13, and `tests/unit/integrations/test_oidc.py`.

### Security

- **Fixed a privilege-escalation vulnerability (task F1)**: `api/app.py`'s shared
  authentication helper used to discard the `UserIdentity` that `authenticate()` resolved,
  so every protected endpoint except `create_run` skipped both resource-ownership and
  real-role checks. A caller authenticated as one end user could read another
  organization's Run or HumanGate, and approve someone else's HumanGate outright by
  putting `roles=["approver"]` and an arbitrary `decided_by` in the request body --
  `HumanGateDecisionRequest.decided_by` / `.roles` were client-submitted and only checked
  for the literal string `"approver"`, never against the caller's actual identity. Fixed:
  - the authentication helper now returns `(UserIdentity | None, JSONResponse | None)`
    instead of discarding the identity; every protected endpoint (Run read/cancel/events/
    observability, Gate read/decide, diagnostics, SSE, Actuator, DevTools) receives it;
  - reading or cancelling a Run, and reading or deciding a Gate, now verify the
    authenticated identity's `organization` matches the Run's `user.organization`;
    mismatches return **404** (`RUN_NOT_FOUND` / `GATE_NOT_FOUND`), not 403, so an
    unrelated caller cannot even confirm the resource exists;
  - deciding a Gate with an authenticated identity present requires the request body's
    `decided_by` / `roles` to match that identity exactly (id, and roles as a set); a
    mismatch is rejected with `IDENTITY_MISMATCH` (409) rather than silently overridden,
    and on a match the values actually recorded are the identity's own, not the request
    body's.
  - **Compatibility is preserved**: when no end-user identity is resolved (the default
    `ApiKeyAuthnProvider`, trusted-service mode), `decided_by` / `roles` keep exactly
    their pre-fix, request-body-is-authoritative meaning -- this is the documented trust
    boundary from task E3 (the API key authenticates the calling service, not the end
    user it claims to act for), not a remaining hole.
  See `src/gaia/api/app.py`, `developer-docs/http-api.md`'s new "资源归属：跨组织隔离
  （F1）" and "Human Gate 审批：身份由服务端生成，不信任请求体（F1）" sections,
  `docs/施工图/09-Runtime安全边界与Sandbox.md` §12, and the new
  `tests/integration/test_f1_resource_ownership.py`.

### Added

- Added an authentication SPI, `gaia.spi.auth.AuthnProvider` (task E3): a single
  `async authenticate(headers) -> UserIdentity | None` method with three outcomes that must
  never be conflated -- raising `AuthenticationError` rejects the request (401) before it
  reaches Runtime; returning a `UserIdentity` makes it the single source of truth, overriding
  `RunRequest.user` outright (no field merging); returning `None` authenticates the caller as
  a trusted service with no end-user identity, so `RunRequest.user` applies exactly as
  submitted. If a request body's `user` disagrees with an authenticated `UserIdentity`, the
  request is now rejected with the new `IDENTITY_MISMATCH` error code instead of being
  silently overridden -- silent override would let a caller believe it acted as the identity
  it claimed while the system recorded a different one. `create_app` gains an optional
  `authn: AuthnProvider | None = None` parameter; not passing it is byte-identical to the
  previous behaviour via the new default `ApiKeyAuthnProvider`, which wraps the existing
  `X-Gaia-Api-Key` check and returns `None` on a valid key. `RunRequest.user` is
  client-submitted, untrusted input whose `roles` field feeds directly into
  `gaia.runtime.safety.validate_roles` and per-tool `required_roles` checks, so
  `ApiKeyAuthnProvider`'s trust boundary is stated plainly: it authenticates the calling
  *service*, not the end user the service claims to act for, and Gaia does not cross-check
  that claim in API-key mode. No SSO/OIDC/mTLS implementation is included -- this is the SPI
  and its one default implementation. The contract now lives in `src/gaia/spi/auth.py` and the
  default implementation in `src/gaia/integrations/api_key.py`; see
  `developer-docs/http-api.md`'s "认证：`AuthnProvider`" section,
  `docs/施工图/09-Runtime安全边界与Sandbox.md` §11, and `tests/integration/test_authn.py`.
- Added typed component access to `GaiaApplication.get_component(component_id, expected=None)`
  (task E1): passing `expected` asserts the port a caller genuinely requires and raises a
  `TypeError` carrying `COMPONENT_TYPE_MISMATCH:<component_id> expected <Type>, got
  <ActualType>` when the registered component doesn't satisfy it, instead of handing back an
  instance the caller can't actually use. `isinstance()` handles concrete classes and
  `@runtime_checkable` Protocols directly; plain structural Protocols without that decorator
  (e.g. `gaia.spi.model.ModelProvider`) fall back to the same attribute-presence check
  `@runtime_checkable` performs internally, so `expected` works without requiring every SPI
  port to add the decorator. `RuntimeError("APPLICATION_NOT_STARTED")`,
  `KeyError("COMPONENT_NOT_FOUND:<id>")`, and the new `TypeError` are now all registered in
  `error_catalog.py` with operator guidance instead of being errors outside the catalog
  system. `api/devtools_prompts.py`'s Prompt-provider lookups and `api/app.py`'s
  `_optional_component` (used for the `runtime-assembler` component) now pass `expected`.
  See `src/gaia/application/core.py`, `src/gaia/diagnostics/error_catalog.py`, and
  `tests/unit/application/test_lifecycle.py`.
- Added a cross-replica lease and bounded, budgeted recovery for
  `PersistentRuntimeEngine.startup_recover` (task D1/D1.1). Previously,
  `startup_recover` ran unguarded, so two PostgreSQL replicas starting at the same time
  could both recover -- and potentially re-execute uncertain writes for -- the same Runs.
  Migration `0014_runtime_leases` adds table `runtime_leases` (used by new
  `gaia.persistence.leases.LeaseStore`: `try_acquire`/`renew`/`release`, portable across
  SQLite and PostgreSQL) and column `side_effect_commands.recovery_attempts`.
  `startup_recover` now acquires the `"runtime-recovery"` lease before doing any work
  (skips recovery with a warning if it can't), processes every phase (handoffs, commands,
  ActionPlans, continuations) in ordered, cursor-advancing batches of 50, and renews the
  lease every 10 processed items -- a failed renewal stops recovery immediately and returns
  the work completed so far, without raising or continuing under a lease it may no longer
  hold. Each write recovery strategy now has an explicit recovery budget:
  `reconcilable`/`idempotent` get up to 3 recovery-triggered attempts before giving up;
  `at_most_once_manual` gets zero, since "execute at most once, then a human decides" has no
  second attempt to budget for. Exhausting the budget moves the command to a new terminal
  `CommandStatus.NEEDS_ATTENTION`, excluded from future recovery, and its 24h count is
  surfaced via `/actuator/runtime`'s new `needs_attention` field -- there is deliberately no
  API to move a command out of this status; that requires an independent authorization and
  audit design. See `developer-docs/mechanisms.md`'s "启动恢复：租约、批处理与
  `needs_attention`" section, `tests/unit/test_leases.py`,
  `tests/integration/test_runtime_recovery_batching.py`, and the strategy-budget tests in
  `tests/integration/test_runtime_reliability.py`.
- Added config-driven, monotonic policy overrides (task C2):
  `runtime.policy_overrides` in `gaia.yaml`, keyed by `scenario_id`
  (`gaia.config.models.PolicyOverrideSettings`: `write_mode`, `max_steps`,
  `max_model_calls`, `max_duration_seconds`, `deny_tools`), lets operations tighten a
  scenario's `ExecutionPolicy` without a code release -- force approval on a write, cut a
  budget, deny a tool. Every field may only make the policy *stricter*: an override that
  could loosen it would turn a config file into a way to bypass the controls the framework
  exists to enforce. `gaia.runtime.policy.apply_policy_override` enforces this and raises
  `ValueError` (prefixed `POLICY_OVERRIDE_INVALID:`, new `ErrorCode.POLICY_OVERRIDE_INVALID`)
  the moment an override would loosen policy -- from `RuntimeAssembler.create_engine`, i.e.
  at application startup, never on a request. `_stricter_write_mode`'s write-mode rank table
  moved from `gaia.runtime.safety` (frozen validation logic; unchanged) to a new public
  `gaia.runtime.policy.stricter_write_mode`, which `safety.py` now imports. A successful
  override's returned policy carries a fingerprint of its effective (actually-changed)
  content as a PEP 440 local version segment -- `f"{policy.version}+ovr.{digest}"` via
  `fingerprint(..., qualified=False)` -- so the recorded `VersionBundle.policy` changes
  whenever governance changes instead of silently lying about which policy produced a
  Run's decision; an override that changes nothing relative to the baseline leaves
  `version` untouched. See `developer-docs/concepts.md`'s "策略收紧覆盖（Policy Override）"
  and `tests/unit/test_policy_override.py`.
- Added the public `gaia.fingerprint` helper (task C1): a deterministic content digest
  (`fingerprint(source, ...) -> 'sha256:3f1a9c0d2e4b'`, or the bare digest with
  `qualified=False`) that `@scenario(rules_version=..., ...)` and friends can derive from
  actual content -- a file, a module/class/function's source, or a `Mapping`/`Sequence` as
  canonical JSON -- instead of a hand-typed literal that can silently drift from the code it
  is supposed to describe. Also added `gaia.testing.gates.VersionBundleGate`, a `QualityGate`
  that fails a test run when the subject's version-bundle fields (read from
  `GateContext.subject`) don't match an expected mapping, so a governance version change can
  be enforced as an explicit CI check instead of a silent surprise in the audit trail.
  `examples/function_task/flows.py`'s `request_publish` scenario now derives `rules_version`
  from `fingerprint(tools)`.
- Made every Runtime state write go through an explicit transition table: HumanGate, side-effect
  Command and ActionPlan step transitions now have tables alongside the existing Run table in
  `gaia.runtime.lifecycle`, and illegal transitions raise `RUNTIME_ILLEGAL_TRANSITION` instead of
  silently corrupting state.
- Added `examples/function_task`, a minimal fully declarative reference application (task
  A5): `flows.py` has a read-only `@scenario` and a write `@scenario` that proposes a
  `ScenarioSideEffect` via `ScenarioResponse.propose(...)`, `tools.py` has one `@read_tool`
  and one `@write_tool` that mutates an in-memory resource table, and `gaia.yaml` wires them
  up with the `core-runtime` / `model-mock` / `scenario-runtime` Starters and
  `scenarios.modules` -- no application composition code at all. `app.py` is 9 non-empty
  lines and only calls `create_app(gaia_application=GaiaApplication.from_config(...))`. See
  `tests/integration/test_function_task_example.py` for the end-to-end HumanGate flow
  (create run, approve the pending gate, confirm the write actually executed) and
  `developer-docs/getting-started.md` for how it contrasts with `examples/controlled_task`'s
  custom `ScenarioRunner` SPI style.
- The built-in `model-mock` and `model-openai-compatible` Starters now register real
  `ModelProvider` instances instead of placeholder marker dicts, closing the gap the
  `scenario-runtime` Starter (below) left open for model-backed scenarios. `model-mock`
  registers a new framework-owned `gaia.model_gateway.mock.DeterministicMockProvider` --
  generic, no domain-specific parsing, deterministic output derived from the requested
  schema's fields and the input messages. `model-openai-compatible` registers a real
  `gaia.model_gateway.openai_compatible.OpenAICompatibleProvider`, resolving
  `config.model.api_key` via `resolve_secret` only inside the Starter's factory closure so
  the resolved key lives solely on that provider instance and never reaches a
  `ComponentDescriptor` or `actuator_snapshot()`. Also added
  `gaia.model_gateway.model_endpoint_profile_from_config`, which builds the
  `ModelEndpointProfile` a scenario needs to call `ctx.model.generate_structured(...)` /
  `generate_stream(...)` directly from `config.model`. Together these make declarative
  `gaia.yaml` applications that use `ctx.model` work end to end with no
  application-supplied `model_provider` -- both read-only and model-backed scenario types
  now need zero hand-wired composition (this is milestone M1). WORKFLOW / CONTEXT / POLICY
  Starters are unaffected and still register placeholder marker dicts.
- Added a built-in `scenario-runtime` Starter that, when `scenarios.modules` is configured,
  discovers the declared scenario/tool modules and registers the `RuntimeAssembler` (from the
  A3 assembly consolidation) as a singleton `ComponentKind.RUNTIME` component named
  `runtime-assembler`. `create_app` now falls back to this component whenever an application
  does not pass an explicit `dependencies` argument, so a purely declarative `gaia.yaml` can
  serve real HTTP runs without any hand-written composition code; explicitly supplied
  `dependencies` continue to take priority unchanged. Optional collaborators (model provider,
  prompt provider, retriever) are only injected from the component graph when the resolved
  instance actually satisfies the corresponding port; see the `model-mock` /
  `model-openai-compatible` entry above for how the MODEL side of that port is now filled
  with a real `ModelProvider` rather than a placeholder marker dict.
- Added `gaia.starters.scenario_discovery.discover_scenarios`, a deterministic module scanner
  that imports declared `scenarios.modules` paths and inventories the `@scenario` / `@read_tool`
  / `@write_tool` functions each module defines, rejecting duplicate scenario IDs or tool names.
  Import failures are reported as `SCENARIO_MODULE_NOT_FOUND` when the declared module path
  itself does not exist, and as the new `SCENARIO_MODULE_IMPORT_FAILED` when the module exists
  but one of its own imports fails, so operators are pointed at the actual broken dependency
  instead of the `scenarios.modules` config. Discovery is now wired into application startup by
  the `scenario-runtime` Starter described above.
- Added a `scenarios.modules` configuration key to declare which modules contain `@scenario` /
  `@read_tool` / `@write_tool` decorated functions; discovery and runtime wiring are now provided
  by the `scenario-runtime` Starter described above.
- Added `@agent_handler(agent_id, allowed_handoffs=...)` and `@continuation_handler(name)` (task
  A6), the declarative counterparts to `ScenarioResponse.handoff_to(...)` and
  `continue_with=...`: same no-side-effects pattern as `@scenario` -- they only attach immutable
  metadata (`AgentHandlerSpec`, a continuation name string) and require an async handler.
  `@scenario` also gained an `allowed_handoffs: tuple[str, ...] = ()` parameter so a Scenario can
  declare its own outgoing handoff edges. `discover_scenarios` now also collects these into
  `DiscoveredScenarios.agent_handlers` / `agent_routes` / `continuation_handlers`, rejecting a
  duplicate `agent_id` (`AGENT_HANDLER_DUPLICATE`) or duplicate continuation name
  (`CONTINUATION_HANDLER_DUPLICATE`), and reusing `HANDOFF_TARGET_NOT_FOUND` when a route names an
  agent no `@agent_handler` declares -- all fail-fast at assembly time, not at request time. The
  routing table has no implicit default edges: an agent or scenario that does not declare
  `allowed_handoffs` has no outgoing edge at all. `scenario-runtime`'s `ScenarioRuntimeStarter`
  wires the discovered handlers/routes into `RuntimeAssembler`, and `RuntimeAssembler.create_engine`
  now assembles each `FunctionScenarioRunner`'s own `"scenario"` route entry from that runner's own
  spec while sharing the agent-to-agent routes across every scenario in a multi-scenario
  application. `examples/function_task` now also covers a handoff (`escalate_resource` ->
  `resource_specialist`) and a post-write continuation (`request_publish_and_notify` ->
  `notify_after_publish`) end to end, with `app.py` unchanged.
- Added durable named Continuation handlers so approved write results and completed ActionPlans can
  drive later model calls, Agent Handoffs, or additional controlled operations across restarts.
- Added explicit `reconcilable`, `idempotent`, and `at_most_once_manual` Write Tool recovery
  strategies for modern and legacy enterprise APIs.
- Added durable per-Run step, model-call, and active-duration budgets shared by Scenario, Agent,
  Read/Write Tool, HumanGate recovery, and bounded output correction.
- Added Runtime-native Agent Handoff with explicit routes, persistent recovery state, shared
  RunBudget, and normal Write Tool / HumanGate integration.
- Added opt-in structured-output correction for schema errors and explicitly correctable output
  validators; safety blocks are never reasked.
- Added TypeScript and Java/Spring client integration guidance, restored the Java reference source,
  and added a Java compile gate to CI.
- Added one five-stage Guardrail declaration across `GaiaAppBuilder`, durable Runtime, and
  `ScenarioTestHarness`; the HR Showcase now exercises a real local Guardrails AI output validator.
- Added pre-approval write-input protection and post-execution write-output protection with
  auditable `blocked` run semantics.
- Added a Codex-native change-set workflow that keeps implementation, tests, documentation,
  generated contracts, and release impact synchronized.
- Added clean-environment GitHub quality and service-integration workflows for private development.
- External-model, scheduled, and release workflows remain disabled during the development phase.
- Consolidated local PostgreSQL and Redis into one optional development-infrastructure Compose;
  Gaia applications, Dev Console, and documentation now use native development commands.
- Registered the HR reference Showcase under the three business-facing Quick Start templates and
  added configurable Dev Console API and Showcase targets for local application development.
- Added auditable Codex hook forwarding for parent workspaces plus tracked Git commit and push gates,
  so missing workspace discovery can no longer silently bypass local Change Set verification.
- Added a phased business-builder experience plan covering first-class Read Tool execution,
  simplified application composition, pending approval output, deterministic multi-action plans,
  testing, client integration, and the future boundary for mature ReAct frameworks.
- Added unified Read/Write Tool registration and scoped read execution with role, environment,
  timeout, guardrail, and payload-free invocation evidence.
- Added waiting-state business results, redacted approval views, deterministic sequential
  ActionPlan execution, restart recovery, and partial-failure reporting.
- Added `GaiaAppBuilder`, an in-process `ScenarioTestHarness`, and a typed TypeScript Runtime client.
- Added run-scoped Retrieval identity binding, starter datasets for normal, boundary, and dependency
  cases.

### Changed

- `GaiaApplicationContext.framework_version` (and the same field on `/actuator/info`) now
  comes from installed package metadata instead of a hand-typed `"0.1.0"` literal (task E2):
  `application/core.py`'s `_framework_version()` reads `importlib.metadata.version
  ("gaia-framework")` and falls back to a clearly-marked `"0.0.0+dev"` when the package isn't
  installed (e.g. a bare source checkout), so the reported version can no longer silently
  drift from `pyproject.toml`. `config/models.py`'s `ApplicationConfig.version` default (an
  *application's* own version, not the framework's) and the FastAPI `app`'s `version="0.1.0"`
  (the HTTP API's own version) are unrelated fields and were left unchanged, as was the
  `templates/project.py` generated-project content. See
  `tests/unit/application/test_lifecycle.py`, which now asserts the semantic property
  (non-empty, PEP 440 shaped) instead of the old literal value.
- Documented the deployment topology boundary the framework actually guarantees today
  (task D2, milestone M6 of `docs/施工图/13-重构施工图-装配打通与Runtime拆解.md`): the
  SQLite profile is single-process/single-replica; the PostgreSQL profile lets the API
  service run multiple replicas, but `startup_recover` is serialized by the
  `"runtime-recovery"` lease added in D1 (60s TTL, renewed every 10 processed items, and
  never silently re-acquired once expired -- see `gaia.persistence.leases.LeaseStore`); the
  Outbox dispatcher claims work under its own per-event row lease
  (`locked_by`/`locked_until`, `SKIP LOCKED` on PostgreSQL) and is independently
  multi-replica safe. States plainly that there is **no** cross-replica coordination of
  ordinary Run execution -- the lease only serializes startup recovery, not steady-state
  request handling, which relies on per-request idempotency and per-command CAS instead.
  No code changed. See `docs/施工图/09-Runtime安全边界与Sandbox.md` §10,
  `developer-docs/mechanisms.md`, and `README.md`.
- `gaia init` (and the Dev Console's guided project-init flow) now generates fully declarative
  projects instead of the previous `GaiaAppBuilder(...).scenarios(...).prompts(...).dependencies()`
  hand-wiring (task A7, milestone M2 of `docs/施工图/13-重构施工图-装配打通与Runtime拆解.md`).
  The generated `gaia.yaml` declares `scenarios.modules` (pointing at the generated
  `<package>.scenarios.<hello|knowledge|approval>` module) and always includes the
  `scenario-runtime` Starter; the generated `app.py` shrinks to importing `create_app` /
  `GaiaApplication` / `resolve_config_path` and calling
  `create_app(gaia_application=GaiaApplication.from_config(resolve_config_path()))` -- no
  `GaiaAppBuilder`, no explicit `dependencies=`, identical across all three scenario templates
  (`basic` / `knowledge` / `approval`). The Prompt Provider (`prompt-file` / `prompt-postgres`)
  and, for the `knowledge` template, the Retriever (`rag-postgres`) are resolved automatically
  from the component graph by `scenario-runtime`, the same mechanism `examples/function_task`
  uses -- no application-supplied lambda needed. See
  `tests/integration/test_project_init_declarative_app.py` for coverage that actually boots each
  generated `app.py` unmodified and serves a real Run (or, for `knowledge`, configures the
  component graph, since real retrieval needs PostgreSQL).
- `gaia check` now reports the error catalog's specific `operator_action` (instead of the
  generic "correct the reported gaia.yaml, profile, secret reference, or Starter issue")
  whenever configuration fails with a `ScenarioDiscoveryError` -- most commonly
  `SCENARIO_MODULE_NOT_FOUND` right after `gaia init`, when the generated package has not
  been installed yet, so `scenarios.modules` cannot be imported. The catalog entry for
  `SCENARIO_MODULE_NOT_FOUND` now names installing the project as the primary fix, not just
  "correct the module path"; the generated project's README and `gaia init`'s own success
  output both now say to run `uv sync` before `gaia check` / `gaia dev`. Every other
  `gaia check` failure keeps the generic action unchanged.
- Extracted the durable Runtime engine assembly (spec validation, guardrail pipelines, and the
  model-provider wrapping chain) out of `ApiDependencies.from_scenarios` and into a new
  `gaia.runtime.assembly.RuntimeAssembler`, the single shared assembly path for the decorator API
  and future Runtime starters. Internal refactor; no behavior change.
- Extracted SideEffectCommand creation, execution and result reconciliation out of
  `PersistentRuntimeEngine` (task B2 of
  `docs/施工图/13-重构施工图-装配打通与Runtime拆解.md`) and into a new
  `gaia.runtime.command_execution.CommandExecutor`, which the engine now holds as
  `self._commands` and delegates to. `CommandExecutor` is the sole owner of the per-command
  `WriteAdapter` cache and the side-effect success counter (`PersistentRuntimeEngine
  .side_effect_success_count` now forwards to it). Pure internal move: command status writes
  still go through `gaia.runtime.lifecycle.validate_command_transition`, and event ordering,
  transaction boundaries, and the engine's public method names/signatures are unchanged.
- Extracted ActionPlan lifecycle management (starting a plan, advancing it, and per-step status
  bookkeeping) out of `PersistentRuntimeEngine` (task B3 of
  `docs/施工图/13-重构施工图-装配打通与Runtime拆解.md`) and into a new
  `gaia.runtime.action_plan.ActionPlanManager`, which the engine now holds as `self._plans` and
  delegates to. `CommandExecutor` reaches the same single instance through its existing engine
  back-reference (`self._engine._plans`) rather than holding a second one, so there is exactly one
  `ActionPlanManager` per engine. Pure internal move: action status writes still go through
  `gaia.runtime.lifecycle.validate_action_transition`, and event ordering, transaction boundaries,
  and the engine's public method names/signatures are unchanged.
- Extracted multi-agent Handoff persistence, resolution and crash recovery out of
  `PersistentRuntimeEngine` (task B4 of
  `docs/施工图/13-重构施工图-装配打通与Runtime拆解.md`) and into a new
  `gaia.runtime.handoff.HandoffCoordinator`, which the engine now holds as `self._handoffs` and
  delegates to. `startup_recover` and `_ensure_active_run_budgets` stay on the engine (reserved for
  a later task) and now call `self._handoffs.recover_handoff(...)` instead of a private engine
  method. Pure internal move: Handoff persistence/read ordering, transaction boundaries, and the
  engine's public method names/signatures are unchanged.
- Closed out the B2-B4 engine extraction (task B5 of
  `docs/施工图/13-重构施工图-装配打通与Runtime拆解.md`, milestone M4). No behaviour change:
  verified that the methods B2/B3/B4 moved into `command_execution.py`, `action_plan.py` and
  `handoff.py` exist in exactly one place each (`persistent_engine.py` shrank from 1980 to 1146
  lines with no residual duplicate bodies). Revised the original "<800 lines" size target to
  "≤1200 lines" now that the remaining ~1150 lines are accounted for by public API, core
  orchestration, and a dozen ledger-plumbing methods shared by the three collaborators -- the
  rationale is recorded on the B5 task card, and merging that shared plumbing with the existing
  but production-unused `RuntimeLedger` is tracked separately as the new, still-open B6 task.
  Documented `gaia.runtime.lifecycle` as the authoritative source for legal state transitions in
  `docs/施工图/02-Runtime状态机与事务边界.md` and fixed that document's Run transition table,
  which was missing the `RUNNING -> RUNNING` self-loop the code relies on for ActionPlan
  step advancement and continuation resumption.
- Deleted `gaia.runtime.ledger.RuntimeLedger` (task B6 of
  `docs/施工图/13-重构施工图-装配打通与Runtime拆解.md`, closing out engine decomposition
  milestone M4/工程 B). It duplicated the engine's own Run/event persistence but allocated event
  sequence numbers by reading `max(sequence)` and writing `+1` -- a read-then-write race that two
  concurrent appends could lose (both landing on the same sequence). The engine's own
  `_append_event` allocates atomically via a single `UPDATE runs SET event_sequence =
  event_sequence + 1 RETURNING event_sequence`, which is exactly what migrations
  `0002_run_event_counter`/`0003_backfill_run_event_counter` introduced the counter column for.
  `RuntimeLedger` had no production caller -- only `tests/integration/test_persistence.py` used
  it -- so keeping it around was a duplicate-implementation hazard with the known-bad half still
  reachable by name. That test now exercises the same property (a Run and its Event surviving
  across sessions, with a correctly allocated sequence) through `PersistentRuntimeEngine
  .transition()`, the real production path, instead. No behavior change to the engine.
- Output-guarded model streams now buffer and evaluate the complete response once before releasing
  content; unguarded streams remain provider-native pass-through.
- Renamed the lightweight process-local Agent helper to `InMemoryHandoffOrchestrator`; the previous
  name remains as a compatibility alias.
- Write Tool roles now default to no required role, and Runtime supplies a minimal redacted
  ApprovalView when applications do not provide one.
- Removed the model-only text-processing option from the business-facing Quick Start. It remains a
  developer `basic` skeleton, while business builders start from knowledge-backed answers or
  controlled business operations.
- Updated business-facing Quick Start examples: the generic text template is no longer coupled to
  a resume example, and the controlled-operation reference now demonstrates onboarding access
  provisioning instead of leave submission.
- Updated Dev Console Run inspection to present business output, action progress, and tool evidence
  without rendering internal write payloads.
- Updated generated write scenarios to create proposals through the scoped Tool context, and added
  CI drift checks between the OpenAPI Runtime contracts and the TypeScript client.
