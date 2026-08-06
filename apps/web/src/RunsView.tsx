import { RefreshCw, Search } from "lucide-react";
import { useEffect, useState } from "react";

import { Metric, StructuredView, displayValue, shorten } from "./StructuredView";
import { RunEvidence } from "./RunEvidence";
import { guardrailStageLabel } from "./labels";
import { message } from "./format";
import { findApprovedGate, findDecidedAgainstGate } from "./humanGates";
import type {
  DiagnosticBundle,
  GuardrailDecision,
  HumanGate,
  RunGuardrailObservability,
  RunModelObservability,
  RunPage,
  RunSnapshot,
  RunToolObservability,
  RuntimeSummary,
} from "./types";
import {
  decideGate,
  getDiagnosticBundle,
  getEvents,
  getGate,
  getGuardrailDecisions,
  getModelInvocations,
  getRun,
  getRunHumanGates,
  getToolInvocations,
  listRuns,
} from "./api";

type State = Record<string, unknown>;

export function OperationsOverview({ summary }: { summary: RuntimeSummary }) {
  return (
    <>
      {/* Counts, not a success rate. Leading with 成功率 made every Run a
          control had deliberately refused read as a shortfall: three seeded
          demo Runs, two of them correctly blocked, showed as "成功率 33.3%".
          被控制拦下 is its own fact because it is neither success nor failure,
          and 失败 counts only Runs that actually broke. */}
      <div className="summary-grid">
        <Metric
          label="已完成"
          value={String(summary.status_counts.succeeded ?? 0)}
        />
        <Metric label="被控制拦下" value={String(summary.stopped_by_control)} />
        <Metric label="待人工确认" value={String(summary.pending_human_gates)} />
        <Metric label="失败" value={String(summary.status_counts.failed ?? 0)} />
      </div>
      {/* Capacity and dependency numbers fold away. On a small deployment most
          of them are `0` or `-`, and ten such fields sitting above the Run list
          buried the thing this page is named after. They matter when an operator
          is chasing saturation, so they are one click away, not deleted. */}
      <details className="capacity-details">
        <summary>运行时容量与依赖</summary>
      <table>
        <tbody>
          <tr>
            <th>活跃 Run</th>
            <td>{summary.active_runs}</td>
            <th>停滞 Run</th>
            <td>{summary.stale_runs}</td>
          </tr>
          <tr>
            <th>最久人工等待</th>
            <td>{formatAge(summary.oldest_pending_gate_age_seconds)}</td>
            <th>人工等待 p95</th>
            <td>{formatDuration(summary.human_gate_wait.p95_ms)}</td>
          </tr>
          <tr>
            <th>数据库连接</th>
            <td>
              {summary.database.checked_out ?? "-"} /{" "}
              {summary.database.pool_size ?? "-"}
            </td>
            <th>数据库等待 / 锁等待</th>
            <td>
              {summary.database.waiting_connections ?? "-"} /{" "}
              {summary.database.lock_waiting_connections ?? "-"}
            </td>
          </tr>
          <tr>
            <th>Outbox 待发送</th>
            <td>{summary.outbox.pending}</td>
            <th>重试 / 死信</th>
            <td>
              {summary.outbox.retrying} / {summary.outbox.dead_letter}
            </td>
          </tr>
          <tr>
            {/* Throughput sits with the other capacity numbers rather than in
                the headline: the headline answers "what happened to these
                Runs", and a latency percentile is not an answer to that. */}
            <th>耗时 p95</th>
            <td>{formatDuration(summary.run_duration.p95_ms)}</td>
            <th>耗时 p50</th>
            <td>{formatDuration(summary.run_duration.p50_ms)}</td>
          </tr>
        </tbody>
      </table>
      </details>
    </>
  );
}

export function IssueTable({ issues }: { issues: RuntimeSummary["issues"] }) {
  if (!issues.length) {
    return (
      <div className="runs-clear-state">
        <span className="runs-clear-mark" aria-hidden="true">✓</span>
        <div>
          <strong>当前没有需要人工处理的 Run</strong>
          <p>最近窗口内没有失败或等待人工确认的运行。</p>
        </div>
      </div>
    );
  }
  return (
    <>
      <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Run</th>
            <th>场景</th>
            <th>状态</th>
            <th>瓶颈</th>
            <th>持续时间</th>
            <th>错误码</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((issue) => (
              <tr key={issue.run_id}>
                <td>
                  <span className="run-id" title={issue.run_id}>
                    {shorten(issue.run_id, 16)}
                  </span>
                </td>
                <td>{issue.scenario_id}</td>
                <td>{issue.status}</td>
                <td>{bottleneckLabel(issue.bottleneck)}</td>
                <td>{formatAge(issue.age_seconds)}</td>
                <td>{issue.error_code ?? "-"}</td>
              </tr>
          ))}
        </tbody>
      </table>
      </div>
    </>
  );
}

export function RunConsole({
  summary,
  refreshSummary,
  autoSelectRunId,
  onAutoSelectHandled,
}: {
  summary: RuntimeSummary;
  refreshSummary: () => Promise<void>;
  // Set by the demo landing page's "看证据" button (via `Console`) to open a
  // specific Run's detail panel without the reader pasting a Run ID. `null`
  // once there is nothing pending -- this is a one-shot request, not a
  // controlled value, so it is consumed (`onAutoSelectHandled`) immediately.
  autoSelectRunId?: string | null;
  onAutoSelectHandled?: () => void;
}) {
  // The recent-runs list is what makes the 运行 view browsable without
  // already knowing a Run ID -- see H2. It is deliberately separate state
  // from the by-ID lookup below: loading more pages must never disturb
  // whichever Run is currently open in the detail panel.
  const [runItems, setRunItems] = useState<RunSnapshot[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [runsError, setRunsError] = useState("");
  const [runsLoading, setRunsLoading] = useState(false);
  // Only populated for rows `humanApprovalLabel` cannot resolve from
  // `RunSnapshot` fields alone -- see the fetch effect below and D2's
  // `GET /v1/runs/{run_id}/human-gates`.
  const [gateConfirmations, setGateConfirmations] = useState<
    Record<string, HumanGate[] | "error">
  >({});

  const [runId, setRunId] = useState("");
  const [gateId, setGateId] = useState("");
  const [result, setResult] = useState<RunSnapshot | null>(null);
  const [events, setEvents] = useState<State[]>([]);
  const [gate, setGate] = useState<HumanGate | null>(null);
  const [gates, setGates] = useState<Record<string, HumanGate>>({});
  // True when at least one HumanGate id was discovered (from the run, its
  // action plan, or the diagnostics bundle) but its record could not be
  // fetched -- e.g. already pruned, or the bundle endpoint itself failed.
  // The Evidence tab must never read this the same as "no gate ever existed".
  const [gateLoadIncomplete, setGateLoadIncomplete] = useState(false);
  const [modelObservability, setModelObservability] =
    useState<RunModelObservability | null>(null);
  const [guardrailObservability, setGuardrailObservability] =
    useState<RunGuardrailObservability | null>(null);
  const [toolObservability, setToolObservability] =
    useState<RunToolObservability | null>(null);
  // Evidence is the default, not merely the first tab: the first thing to know
// about a Run is the authority it ran under, not what it returned.
  const [detailTab, setDetailTab] = useState<RunDetailTab>("evidence");
  const [notice, setNotice] = useState("");

  // Accepts an explicit id so a run-list row can jump straight to its detail
  // without waiting on a `setRunId` state update to land first; the by-ID
  // lookup button still calls this with no argument and uses `runId` state.
  async function inspect(id: string = runId) {
    try {
      // The diagnostics bundle is best-effort: it may 404 for very old runs,
      // and the endpoint can be unavailable in some deployments. Either way
      // the rest of the panel must still render -- so failures here resolve
      // to `null` instead of rejecting the whole `Promise.all`.
      const [run, runEvents, observations, tools, guardrails, bundle] = await Promise.all([
        getRun(id),
        getEvents(id),
        getModelInvocations(id),
        getToolInvocations(id),
        getGuardrailDecisions(id),
        getDiagnosticBundle(id).catch((): DiagnosticBundle | null => null),
      ]);
      setResult(run);
      setEvents(runEvents as unknown as State[]);
      setModelObservability(observations);
      setToolObservability(tools);
      setGuardrailObservability(guardrails);
      // Reset to 证据 on every lookup, not just on first mount: a Run is always
      // reached through this query, so the initial useState value never applies.
      setDetailTab("evidence");
      setNotice("");

      // Evidence tab needs whichever HumanGate(s) this run went through, so an
      // approver identity can be attributed to a specific decided gate instead
      // of being read off the run itself (the run never carries `decided_by`).
      // `pending_gate_id` and `action_plan[].gate_id` both go missing the
      // moment a run *completes* -- exactly the runs an auditor looks at --
      // so the diagnostics bundle's `human_gates[]` (keyed by run, not by
      // in-flight state) is included as a third source. Ids are deduplicated
      // and each is still fetched individually via `getGate`, because the
      // bundle's own gate entries omit `decided_by`.
      const bundleGateIds = bundle?.human_gates.map((entry) => entry.gate_id) ?? [];
      const gateIds = Array.from(
        new Set(
          [
            run.pending_gate_id,
            ...(run.action_plan?.actions.map((action) => action.gate_id) ?? []),
            ...bundleGateIds,
          ].filter((id): id is string => Boolean(id)),
        ),
      );
      const fetchedGates = await Promise.allSettled(gateIds.map((id) => getGate(id)));
      const gateMap: Record<string, HumanGate> = {};
      let anyGateUnfetchable = false;
      fetchedGates.forEach((outcome, index) => {
        if (outcome.status === "fulfilled") {
          gateMap[gateIds[index]] = outcome.value;
        } else {
          // A gate id we *know* exists (from the run, its plan, or the
          // bundle) but couldn't load -- e.g. already pruned, or a transient
          // failure. The Evidence tab must report this as "could not be
          // verified", never silently collapse it into "no gate existed".
          anyGateUnfetchable = true;
        }
      });
      setGates(gateMap);
      setGateLoadIncomplete(anyGateUnfetchable);
    } catch (cause) {
      setNotice(message(cause));
    }
  }

  async function inspectGate() {
    try {
      setGate(await getGate(gateId));
      setNotice("");
    } catch (cause) {
      setNotice(message(cause));
    }
  }

  async function decide(decision: "approved" | "rejected") {
    try {
      setResult(await decideGate(gateId, decision));
      await Promise.all([inspectGate(), refreshSummary()]);
    } catch (cause) {
      setNotice(message(cause));
    }
  }

  async function loadRuns(cursor?: string) {
    setRunsLoading(true);
    try {
      const page: RunPage = await listRuns(cursor);
      setRunItems((current) => (cursor ? [...current, ...page.items] : page.items));
      setNextCursor(page.next_cursor);
      setRunsError("");
    } catch (cause) {
      setRunsError(message(cause));
    } finally {
      setRunsLoading(false);
    }
  }

  useEffect(() => {
    void loadRuns();
    // Loaded once on mount; "加载更多" drives subsequent pages explicitly so
    // a background summary refresh never silently re-orders the list under
    // whatever the reader is currently looking at.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Opens whichever Run the demo landing page's "看证据" button asked for,
  // exactly like clicking that Run's row would -- then reports it consumed
  // so this does not re-fire (`autoSelectRunId` is a one-shot request, not a
  // value this component owns).
  useEffect(() => {
    if (!autoSelectRunId) return;
    setRunId(autoSelectRunId);
    void inspect(autoSelectRunId);
    onAutoSelectHandled?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoSelectRunId]);


  // `humanApprovalLabel` can only say "已通过"/"被拒绝" from fields already on
  // `RunSnapshot`; a completed Run built on a `SideEffectProposal` (rather
  // than the multi-step ActionPlan mechanism) clears every one of those
  // fields once it finishes, so the list would otherwise say "未记录" for a
  // Run that plainly was approved. This asks the durable evidence store
  // directly, but only for rows nothing else already answered -- a Run the
  // list already knows was rejected or is still waiting never needs the
  // extra request.
  useEffect(() => {
    const unresolved = runItems.filter(
      (run) =>
        humanApprovalLabel(run) === "未记录" && !(run.run_id in gateConfirmations),
    );
    if (!unresolved.length) return;
    let cancelled = false;
    void Promise.all(
      unresolved.map(async (run) => {
        try {
          return [run.run_id, await getRunHumanGates(run.run_id)] as const;
        } catch {
          return [run.run_id, "error"] as const;
        }
      }),
    ).then((entries) => {
      if (cancelled) return;
      setGateConfirmations((current) => {
        const next = { ...current };
        for (const [id, value] of entries) next[id] = value;
        return next;
      });
    });
    return () => {
      cancelled = true;
    };
  }, [runItems, gateConfirmations]);

  function selectRun(run: RunSnapshot) {
    setRunId(run.run_id);
    void inspect(run.run_id);
  }

  const detailReady =
    result && modelObservability && toolObservability && guardrailObservability;

  return (
    <section className="console-page runs-page">
      <div className="page-title runs-page-title">
        <div>
          <p className="page-eyebrow">运行控制台</p>
          <h1>运行</h1>
          <p className="page-description">
            查看 Gaia 执行了什么、哪些 Run 需要介入，并打开单条运行的完整证据。
          </p>
        </div>
        <button className="primary-button" onClick={refreshSummary}>
          <RefreshCw size={15} />
          刷新
        </button>
      </div>

      <section className="runs-overview" aria-labelledby="runs-overview-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">先看这里</p>
            <h2 id="runs-overview-title">当前运行概况</h2>
          </div>
          <p>先确认是否有需要人工处理或已经失败的运行。</p>
        </div>
        <OperationsOverview summary={summary} />
      </section>

      <section className="runs-attention" aria-labelledby="runs-attention-title">
        <div className="section-heading compact">
          <div>
            <p className="section-kicker">需要行动</p>
            <h2 id="runs-attention-title">待处理 Run</h2>
          </div>
        </div>
        <IssueTable issues={summary.issues} />
      </section>

      {notice && (
        <p className="console-notice" role="alert">
          {notice}
        </p>
      )}
      <RecentRunsList
        items={runItems}
        error={runsError}
        loading={runsLoading}
        nextCursor={nextCursor}
        selectedRunId={result ? result.run_id : null}
        gateConfirmations={gateConfirmations}
        onSelect={selectRun}
        onLoadMore={() => void loadRuns(nextCursor ?? undefined)}
      />

      <section className="run-detail-workspace" aria-labelledby="run-detail-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">选中后查看</p>
            <h2 id="run-detail-title">Run 详情</h2>
          </div>
          {result ? (
            <span className="selected-run-id" title={result.run_id}>
              {shorten(result.run_id, 24)}
            </span>
          ) : null}
        </div>
        {detailReady ? (
          <RunDetail
            result={result}
            events={events}
            gates={gates}
            gateLoadIncomplete={gateLoadIncomplete}
            modelObservability={modelObservability}
            toolObservability={toolObservability}
            guardrailObservability={guardrailObservability}
            tab={detailTab}
            onTabChange={setDetailTab}
          />
        ) : (
          <div className="run-detail-empty">
            <strong>还没有选择 Run</strong>
            <p>
              从上方“最近运行”中点击“查看详情”，这里会展示执行结果、模型与工具调用、安全决策和事件链。
            </p>
          </div>
        )}
      </section>

      <section className="run-operator-tools" aria-labelledby="run-tools-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">精确定位与审批</p>
            <h2 id="run-tools-title">操作工具</h2>
          </div>
          <p>只在列表里找不到目标 Run，或已经拿到 Gate ID 时使用。</p>
        </div>
        <div className="run-tool-grid">
          <section>
          <h2>按 Run ID 查一条运行</h2>
          <p>定位不在最近列表中的历史运行。</p>
          <div className="input-action">
            <input
              aria-label="Run ID"
              value={runId}
              onChange={(event) => setRunId(event.target.value)}
              placeholder="Run ID"
            />
            <button onClick={() => void inspect()} disabled={!runId}>
              查询
            </button>
          </div>
          </section>
          <section>
          <h2>处理一条人工审批</h2>
          <p>输入待审批 Run 提供的 Gate ID，先查看请求，再做决定。</p>
          <div className="input-action">
            <input
              aria-label="Gate ID"
              value={gateId}
              onChange={(event) => setGateId(event.target.value)}
              placeholder="Gate ID"
            />
            <button onClick={inspectGate} disabled={!gateId}>
              查询
            </button>
          </div>
          {/* Deciding requires having loaded the gate first. These buttons used
              to enable on a non-empty text box, so an operator could approve a
              high-risk write by typing an id, without ever seeing what the
              write was, who asked for it, or whether it was still pending.
              An approval nobody looked at is not an approval. */}
          {gate ? (
            <div className="inspection-result">
              <h3>审批详情</h3>
              <GateSummary value={gate} />
              {gate.status === "pending" ? (
                <div className="action-row">
                  <button onClick={() => decide("approved")}>批准这条请求</button>
                  <button className="danger-button" onClick={() => decide("rejected")}>
                    拒绝这条请求
                  </button>
                </div>
              ) : (
                <p className="empty-copy">
                  这条审批已经是「{displayValue(gate.status)}」，不能再次处置。
                </p>
              )}
            </div>
          ) : (
            <p className="empty-copy">
              先查询一条审批，看清它要做什么，才能批准或拒绝。
            </p>
          )}
          </section>
        </div>
      </section>
    </section>
  );
}

// H2: a browsable list above the by-ID lookup, so a first-time reader can
// pick a Run to look at without already holding a UUID. Each row shows just
// enough to choose one -- scenario, status, when, and whether it went
// through human approval -- and an explicit button opens the same detail
// panel the by-ID lookup does, landing on 证据 (see `RunDetail`'s tab default).
//
// No filters, search, or infinite scroll: `next_cursor` plus a single "加载
// 更多" button is enough, per the H2 task card -- extra controls are extra
// decisions for a reader who has never seen this screen before.
function RecentRunsList({
  items,
  error,
  loading,
  nextCursor,
  selectedRunId,
  gateConfirmations,
  onSelect,
  onLoadMore,
}: {
  items: RunSnapshot[];
  error: string;
  loading: boolean;
  nextCursor: string | null;
  selectedRunId: string | null;
  gateConfirmations: Record<string, HumanGate[] | "error">;
  onSelect: (run: RunSnapshot) => void;
  onLoadMore: () => void;
}) {
  return (
    <section className="recent-runs">
      <div className="section-heading">
        <div>
          <p className="section-kicker">选择一条查看</p>
          <h2>最近运行</h2>
        </div>
        <p>打开任意 Run，查看它的结果、证据和完整调用链。</p>
      </div>
      {error && (
        <p className="console-notice" role="alert">
          {error}
        </p>
      )}
      <table className="run-list-table">
        <thead>
          <tr>
            <th>场景</th>
            <th>状态</th>
            <th>人工确认</th>
            <th>更新时间</th>
            <th aria-label="操作" />
          </tr>
        </thead>
        <tbody>
          {items.length ? (
            items.map((run) => (
              <tr
                key={run.run_id}
                className={run.run_id === selectedRunId ? "selected" : ""}
              >
                <td>
                  <div className="component-identity">
                    <strong>{run.scenario_id}</strong>
                    <span className="run-id" title={run.run_id}>
                      {shorten(run.run_id, 16)}
                    </span>
                  </div>
                </td>
                <td>{runStatusLabel(run.status)}</td>
                <td>{humanApprovalLabel(run, gateConfirmations[run.run_id])}</td>
                <td>{new Date(run.updated_at).toLocaleString()}</td>
                <td className="run-row-action">
                  <button
                    className="secondary-button run-open-button"
                    onClick={() => onSelect(run)}
                  >
                    {run.run_id === selectedRunId ? "正在查看" : "查看详情"}
                  </button>
                </td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={5}>{loading ? "正在加载..." : "还没有任何运行"}</td>
            </tr>
          )}
        </tbody>
      </table>
      {nextCursor && (
        <button className="secondary-button" onClick={onLoadMore} disabled={loading}>
          {loading ? "正在加载..." : "加载更多"}
        </button>
      )}
    </section>
  );
}

function runStatusLabel(status: RunSnapshot["status"]): string {
  return (
    {
      received: "已接收",
      validated: "已校验",
      running: "运行中",
      waiting_human: "等待人工确认",
      degraded: "降级",
      blocked: "已阻断",
      succeeded: "已完成",
      failed: "失败",
      cancelled: "已取消",
    }[status] ?? status
  );
}

// Whether -- not who, not when -- this Run went through human approval, for
// a list row that must stay readable at a glance and without a per-row
// request. Reads only fields already present on `RunSnapshot` from the list
// response:
//   - `pending_gate_id` is set while a gate is still awaiting a decision
//     (cleared once decided);
//   - `error.code` durably marks a gate that was decided *against* the run
//     (rejected or expired) -- `_finish` in `persistent_engine.py` writes
//     this to the run itself, so it survives completion regardless of which
//     side-effect mechanism the scenario used;
//   - `action_plan.actions[].gate_id` is the durable "approved" signal, but
//     only for scenarios built on the multi-step ActionPlan mechanism. A
//     scenario that instead resolves a single `SideEffectProposal` (a
//     reference application's write flow, and the one the demo seeding
//     script exercises) never populates `action_plan` at all -- confirmed
//     by curling a live seeded run and finding `action_plan: null` on a Run
//     that plainly went through an approved gate. For that shape there is
//     no field left on `RunSnapshot` once the run completes; only the
//     diagnostics bundle and event stream still know (see `EvidencePanel`,
//     which fetches both).
//
// Given that gap, this deliberately never returns a confident "no gate" for
// a case it cannot verify -- doing so would be exactly the "affirmative
// lie" H0 fixed in the Evidence tab, just at list scale. "未记录" (not on
// record here) is the same wording the Evidence tab already uses for a
// field that is genuinely absent rather than fabricated as a default; a
// reader who needs to know for certain opens the row, which lands on 证据.
//
// `gates` is the durable-store answer for exactly the case above the
// `RunSnapshot` fields cannot resolve (see D2's `GET
// /v1/runs/{run_id}/human-gates`, fetched only for rows that would otherwise
// fall through to "未记录" -- see the effect in `RunConsole`). `"error"`
// means the fetch itself failed; that is still not evidence of "no gate",
// so it falls through to the same honest "未记录" as never having asked.
function humanApprovalLabel(run: RunSnapshot, gates?: HumanGate[] | "error"): string {
  if (run.pending_gate_id) return "等待中";
  if (run.error?.code === "HUMAN_GATE_REJECTED" || run.error?.code === "HUMAN_GATE_EXPIRED") {
    return "被拒绝";
  }
  if (run.action_plan?.actions.some((action) => action.gate_id)) return "已通过";
  if (Array.isArray(gates)) {
    const approved = findApprovedGate(gates);
    if (approved) return approved.decided_by ? `已通过 · ${approved.decided_by}` : "已通过";
    const decidedAgainst = findDecidedAgainstGate(gates);
    if (decidedAgainst) return "被拒绝";
  }
  return "未记录";
}

type RunDetailTab = "evidence" | "result" | "model" | "tools" | "guardrails" | "events";

function RunDetail({
  result,
  events,
  gates,
  gateLoadIncomplete,
  modelObservability,
  toolObservability,
  guardrailObservability,
  tab,
  onTabChange,
}: {
  result: RunSnapshot;
  events: State[];
  gates: Record<string, HumanGate>;
  gateLoadIncomplete: boolean;
  modelObservability: RunModelObservability;
  toolObservability: RunToolObservability;
  guardrailObservability: RunGuardrailObservability;
  tab: RunDetailTab;
  onTabChange: (tab: RunDetailTab) => void;
}) {
  // "证据" leads the tab list -- it answers "under what authority did this run
  // execute", which is the headline claim of the Evidence tab, not an
  // afterthought bolted onto observability tabs that already existed.
  const tabs: Array<[RunDetailTab, string]> = [
    ["evidence", "证据"],
    ["result", "运行结果"],
    ["model", "模型调用"],
    ["tools", "工具调用"],
    ["guardrails", "安全决策"],
    ["events", "事件链"],
  ];
  return (
    <div className="run-detail">
      <div className="workspace-tabs" role="tablist" aria-label="运行详情">
        {tabs.map(([id, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? "selected" : ""}
            onClick={() => onTabChange(id)}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "evidence" ? (
        <div className="inspection-result">
          <RunEvidence
            result={result}
            events={events}
            gates={gates}
            gateLoadIncomplete={gateLoadIncomplete}
            toolObservability={toolObservability}
            guardrailObservability={guardrailObservability}
          />
        </div>
      ) : null}
      {tab === "result" ? (
        <div className="inspection-result">
          <RunOutcomePanel value={result} />
        </div>
      ) : null}
      {tab === "model" ? (
        <ModelObservationPanel value={modelObservability} />
      ) : null}
      {tab === "tools" ? (
        <ToolObservationPanel value={toolObservability} />
      ) : null}
      {tab === "guardrails" ? (
        <GuardrailObservationPanel value={guardrailObservability} />
      ) : null}
      {tab === "events" ? (
        <div className="event-list">
          {events.map((event) => (
            <div key={String(event.sequence ?? event.event_id)}>
              <span className="event-sequence">
                {String(event.sequence ?? "-")}
              </span>
              <div>
                <strong>{String(event.step ?? "event")}</strong>
                <span>
                  {displayValue(event.status)} · {String(event.actor ?? "-")}
                </span>
              </div>
              <time>{displayValue(event.timestamp)}</time>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// Fields of VersionBundle other than `policy` (see
// `gaia.runtime.policy.freeze_version_bundle`), in the order that function
// assembles them. Each is either a content fingerprint (`sha256:...`, from
// `gaia.fingerprint`) or a hand-typed literal -- the panel
// below renders whichever it actually is instead of dressing up a literal as
// a fingerprint.
function RunOutcomePanel({ value }: { value: RunSnapshot }) {
  return (
    <div className="run-outcome">
      <div className="summary-grid compact-summary">
        <Metric label="状态" value={displayValue(value.status)} />
        <Metric label="场景" value={value.scenario_id} />
        <Metric
          label="待确认动作"
          value={String(
            value.action_plan?.actions.filter(
              (item) => item.status === "waiting_human",
            ).length ?? (value.pending_gate_id ? 1 : 0),
          )}
        />
        <Metric
          label="已完成动作"
          value={String(
            value.action_plan?.actions.filter(
              (item) => item.status === "succeeded",
            ).length ?? 0,
          )}
        />
        <Metric
          label="后续处理"
          value={
            value.continuation
              ? value.continuation.ready
                ? `准备继续 · ${value.continuation.handler}`
                : `等待动作结果 · ${value.continuation.handler}`
              : value.handoff
                ? `Agent · ${value.handoff.current_agent}`
                : "-"
          }
        />
      </div>
      {value.pending_result ? (
        <section className="outcome-section">
          <h3>{value.status === "waiting_human" ? "已生成，等待确认" : "业务草稿"}</h3>
          <StructuredView value={value.pending_result} />
        </section>
      ) : null}
      {value.action_plan ? (
        <section className="outcome-section">
          <h3>受控执行计划</h3>
          <table>
            <thead>
              <tr>
                <th>步骤</th>
                <th>系统能力</th>
                <th>状态</th>
                <th>风险</th>
                <th>结果</th>
              </tr>
            </thead>
            <tbody>
              {value.action_plan.actions.map((action) => (
                <tr key={action.step_id}>
                  <td>
                    <strong>{action.approval_view?.title ?? action.step_id}</strong>
                    {action.depends_on.length ? (
                      <span className="table-secondary">
                        依赖 {action.depends_on.join("、")}
                      </span>
                    ) : null}
                  </td>
                  <td>{action.tool_name}</td>
                  <td>{actionStatusLabel(action.status)}</td>
                  <td>{displayValue(action.risk_level)}</td>
                  <td>{action.error_code ?? (action.result ? "已返回" : "-")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
      {value.result ? (
        <section className="outcome-section">
          <h3>最终结果</h3>
          <StructuredView value={value.result} />
        </section>
      ) : null}
      {value.error ? (
        <section className="outcome-section outcome-error">
          <h3>{value.error.message}</h3>
          <p>{value.error.operator_action}</p>
          <span>{value.error.code}</span>
        </section>
      ) : null}
    </div>
  );
}

function GateSummary({ value }: { value: HumanGate }) {
  const presentation = value.approval_view;
  return (
    <div className="gate-summary">
      <div className="summary-grid compact-summary">
        <Metric label="状态" value={displayValue(value.status)} />
        <Metric label="风险" value={displayValue(value.risk_level)} />
        <Metric label="申请人" value={value.requested_by} />
        <Metric label="有效期至" value={displayValue(value.expires_at)} />
      </div>
      <h3>{presentation?.title ?? "待确认操作"}</h3>
      <p>{presentation?.summary ?? value.reason}</p>
      {presentation?.risk_explanation ? (
        <p className="approval-risk">{presentation.risk_explanation}</p>
      ) : null}
      {presentation?.fields ? (
        <StructuredView value={presentation.fields} />
      ) : null}
    </div>
  );
}

function ToolObservationPanel({ value }: { value: RunToolObservability }) {
  return (
    <div className="model-observation">
      <div className="section-heading">
        <div>
          <h3>工具调用</h3>
          <p>展示企业系统读取和受控能力调用，不保存输入与结果正文。</p>
        </div>
      </div>
      <div className="summary-grid compact-summary">
        <Metric label="调用" value={String(value.summary.total)} />
        <Metric label="成功" value={String(value.summary.succeeded)} />
        <Metric label="阻断" value={String(value.summary.blocked)} />
        <Metric label="超时" value={String(value.summary.timed_out)} />
      </div>
      {value.invocations.length ? (
        <table>
          <thead>
            <tr>
              <th>工具</th>
              <th>版本</th>
              <th>状态</th>
              <th>耗时</th>
              <th>原因</th>
            </tr>
          </thead>
          <tbody>
            {value.invocations.map((item) => (
              <tr key={item.invocation_id}>
                <td>{item.tool_name}</td>
                <td>{item.tool_version}</td>
                <td>{displayValue(item.status)}</td>
                <td>{item.duration_ms} ms</td>
                <td>{item.error_code ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="empty-copy">这个 Run 没有工具调用。</p>
      )}
    </div>
  );
}

function actionStatusLabel(status: NonNullable<RunSnapshot["action_plan"]>["actions"][number]["status"]) {
  return {
    pending: "等待执行",
    waiting_human: "等待确认",
    executing: "执行中",
    succeeded: "已完成",
    failed: "失败",
    skipped: "已跳过",
  }[status];
}

function ModelObservationPanel({ value }: { value: RunModelObservability }) {
  return (
    <div className="model-observation">
      <div className="section-heading">
        <div>
          <h3>模型调用</h3>
          <p>仅展示工程指标和版本关联，不保存 Prompt 与响应正文。</p>
        </div>
      </div>
      <div className="summary-grid compact-summary">
        <Metric label="调用" value={String(value.summary.total)} />
        <Metric label="Token" value={String(value.summary.total_tokens)} />
        <Metric
          label="P95 耗时"
          value={
            value.summary.duration.p95_ms === null
              ? "-"
              : `${value.summary.duration.p95_ms} ms`
          }
        />
        <Metric label="重试" value={String(value.summary.retry_count)} />
      </div>
      {value.invocations.length ? (
        <table>
          <thead>
            <tr>
              <th>模型</th>
              <th>Prompt 版本</th>
              <th>状态</th>
              <th>Token</th>
              <th>耗时</th>
            </tr>
          </thead>
          <tbody>
            {value.invocations.map((item) => (
              <tr key={item.invocation_id}>
                <td>
                  <strong>{item.model_id}</strong>
                  <span className="table-secondary">{item.provider}</span>
                </td>
                <td>{item.prompt_version}</td>
                <td>{displayValue(item.status)}</td>
                <td>{item.usage?.total_tokens ?? "-"}</td>
                <td>{item.duration_ms} ms</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="empty-copy">这个 Run 没有模型调用。</p>
      )}
    </div>
  );
}

function GuardrailObservationPanel({
  value,
}: {
  value: RunGuardrailObservability;
}) {
  return (
    <div className="model-observation">
      <div className="section-heading">
        <div>
          <h3>安全决策</h3>
          <p>展示检查结果和规则版本，不保存被检查的业务正文。</p>
        </div>
      </div>
      <div className="summary-grid compact-summary">
        <Metric label="检查" value={String(value.summary.total)} />
        <Metric label="改写" value={String(value.summary.rewritten)} />
        <Metric label="阻断" value={String(value.summary.blocked)} />
        <Metric label="组件异常" value={String(value.summary.errors)} />
      </div>
      {value.decisions.length ? (
        <table>
          <thead>
            <tr>
              <th>检查位置</th>
              <th>规则</th>
              <th>结果</th>
              <th>风险</th>
              <th>原因</th>
              <th>耗时</th>
            </tr>
          </thead>
          <tbody>
            {value.decisions.map((item) => (
              <tr key={item.decision_id}>
                <td>{guardrailStageLabel(item.stage)}</td>
                <td>
                  <strong>{item.guardrail_id}</strong>
                  <span className="table-secondary">
                    v{item.guardrail_version}
                  </span>
                </td>
                <td>{guardrailActionLabel(item.action, item.status)}</td>
                <td>
                  {item.risk_score === null
                    ? "-"
                    : `${Math.round(item.risk_score * 100)}%`}
                </td>
                <td>{item.code ?? "-"}</td>
                <td>{item.duration_ms} ms</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="empty-copy">这个 Run 没有执行安全检查。</p>
      )}
    </div>
  );
}

function guardrailActionLabel(
  action: GuardrailDecision["action"],
  status: GuardrailDecision["status"],
): string {
  if (status === "error") return "检查异常";
  return {
    allow: "放行",
    rewrite: "已改写",
    block: "已阻断",
  }[action];
}


function formatDuration(value: number | null) {
  if (value === null) return "-";
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}


function formatAge(value: number | null) {
  if (value === null) return "-";
  if (value < 60) return `${value} 秒`;
  if (value < 3600) return `${Math.floor(value / 60)} 分钟`;
  return `${Math.floor(value / 3600)} 小时`;
}


function bottleneckLabel(value: string) {
  return {
    human_gate: "人工等待",
    stale_execution: "执行停滞",
    run_error: "运行错误",
  }[value] ?? value;
}
