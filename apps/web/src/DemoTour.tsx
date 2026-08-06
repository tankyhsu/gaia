import { ArrowRight, BriefcaseBusiness, Eye, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { SHOWCASE_EXAMPLES, SHOWCASE_UNAVAILABLE, SHOWCASE_URL } from "./showcase";
import { getEvents, getGuardrailDecisions, getRunHumanGates, getToolInvocations, listRuns } from "./api";
import { findApprovedGate, findDecidedAgainstGate } from "./humanGates";
import { scenarioLabel } from "./labels";
import { errorLabel, roleLabel, RunEvidence } from "./RunEvidence";
import type { HumanGate, RunGuardrailObservability, RunSnapshot, RunToolObservability } from "./types";

// The dedicated first-screen for `make demo`: a reader who has never seen
// Gaia before should be able to say, inside three minutes, what it is and
// what each seeded Run proves. This is deliberately a separate page from
// `#runs` (see `docs/施工图/18-演示可用性施工图.md` task D2) -- the operator
// dashboard's job is triage across many Runs, this page's job is to explain
// three specific ones. It reuses the `#runs` detail panel's Evidence tab
// (via `onViewEvidence`) rather than rendering evidence a second way.

function message(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败";
}

const requestedRunId = new URLSearchParams(location.search).get("run");

const STATUS_LABELS: Record<string, string> = {
  received: "已接收",
  validated: "已校验",
  running: "运行中",
  waiting_human: "等待人工确认",
  degraded: "降级",
  blocked: "已阻断",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

function genericStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

type GateFetchState =
  | { status: "loading" }
  | { status: "loaded"; gates: HumanGate[] }
  | { status: "error" };

type EvidenceFetchState =
  | { status: "idle" }
  | { status: "loading" }
  | {
      status: "loaded";
      events: Record<string, unknown>[];
      tools: RunToolObservability;
      guardrails: RunGuardrailObservability;
    }
  | { status: "error"; message: string };

// Three facts this card must never get wrong, in order of how badly a wrong
// answer would undermine the point of the whole page:
//   1. Never call a `blocked` Run a failure -- that is the exact "control
//      working as designed" the demo exists to show (see 施工图 18's 缺陷 1).
//   2. Never name an approver, or claim "approved"/"rejected", without a
//      decided HumanGate to back it -- an unverified guess is worse than
//      admitting the record was not found.
//   3. Never claim *which* policy rule fired beyond the error code Gaia
//      itself returned -- Gaia's own error catalog is the only source for
//      that, never a guess about what a rule probably checks.
function outcomeLabel(run: RunSnapshot): string {
  if (run.status === "succeeded") return "已完成";
  if (run.error?.code === "HUMAN_GATE_REJECTED" || run.error?.code === "HUMAN_GATE_EXPIRED") {
    return "被人工拒绝";
  }
  if (run.status === "blocked" && run.error?.code) return "被策略拒绝";
  return genericStatusLabel(run.status);
}

function outcomeTone(run: RunSnapshot): "success" | "human" | "policy" | "other" {
  if (run.status === "succeeded") return "success";
  if (run.error?.code === "HUMAN_GATE_REJECTED" || run.error?.code === "HUMAN_GATE_EXPIRED") {
    return "human";
  }
  if (run.status === "blocked" && run.error?.code) return "policy";
  return "other";
}

function scenarioDescription(
  run: RunSnapshot,
  approved: HumanGate | null,
  decidedAgainst: HumanGate | null,
): string {
  const roles = roleLabel(run.user.roles);
  if (approved) {
    return `${roles}发起的高风险写操作，经人工审批后执行完成。`;
  }
  if (decidedAgainst) {
    return `${roles}发起的高风险写操作，被人工审批人拒绝，未执行。`;
  }
  if (run.error?.code) {
    return `${roles}发起的请求，在进入人工审批前被策略终止：${errorLabel(run.error.code)}。`;
  }
  return `${run.scenario_id} 场景的一次运行。`;
}

function controlPointLabel(
  run: RunSnapshot,
  gateState: GateFetchState | undefined,
  approved: HumanGate | null,
  decidedAgainst: HumanGate | null,
): string {
  if (approved) {
    return approved.decided_by
      ? `人工审批网关 · ${approved.decided_by} 批准`
      : "人工审批网关 · 已批准（审批人未记录）";
  }
  if (decidedAgainst) {
    return decidedAgainst.decided_by
      ? `人工审批网关 · ${decidedAgainst.decided_by} 拒绝`
      : "人工审批网关 · 已拒绝（审批人未记录）";
  }
  if (run.error?.code) return `策略校验 · ${errorLabel(run.error.code)}`;
  if (gateState?.status === "loading") return "正在核实...";
  return "未记录";
}

function DemoRunCard({
  run,
  gateState,
  selected,
  onExplain,
}: {
  run: RunSnapshot;
  gateState: GateFetchState | undefined;
  selected: boolean;
  onExplain: () => void;
}) {
  const gates = gateState?.status === "loaded" ? gateState.gates : [];
  const approved = findApprovedGate(gates);
  const decidedAgainst = findDecidedAgainstGate(gates);

  return (
    <article className={`demo-run-card demo-run-card-${outcomeTone(run)} ${selected ? "selected" : ""}`}>
      <header className="demo-run-card-header">
        <span className="demo-run-card-scenario-id" title={run.scenario_id}>
          {scenarioLabel(run.scenario_id)}
        </span>
        <span className="demo-run-card-outcome">{outcomeLabel(run)}</span>
      </header>
      <p className="demo-run-card-scenario">
        {scenarioDescription(run, approved, decidedAgainst)}
      </p>
      <dl className="demo-run-card-meta">
        <div>
          <dt>控制点</dt>
          <dd><strong>{controlPointLabel(run, gateState, approved, decidedAgainst)}</strong>{run.error?.code ? <small>代码 {run.error.code}</small> : null}</dd>
        </div>
        <div>
          <dt>发起者</dt>
          <dd><strong>{roleLabel(run.user.roles)}</strong><small>用户 ID {run.user.id} · 角色 {run.user.roles.join("/") || "未记录"}</small></dd>
        </div>
      </dl>
      <button className="secondary-button" aria-pressed={selected} onClick={onExplain}>
        {selected ? "正在解释" : "查看解释"}
      </button>
    </article>
  );
}

export function DemoTour() {
  const [runs, setRuns] = useState<RunSnapshot[] | null>(null);
  const [error, setError] = useState("");
  const [gateStates, setGateStates] = useState<Record<string, GateFetchState>>({});
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [evidenceState, setEvidenceState] = useState<EvidenceFetchState>({ status: "idle" });

  useEffect(() => {
    let cancelled = false;
    listRuns()
      .then((page) => {
        if (cancelled) return;
        setRuns(page.items);
        setSelectedRunId((current) =>
          current && page.items.some((run) => run.run_id === current)
            ? current
            : requestedRunId && page.items.some((run) => run.run_id === requestedRunId)
              ? requestedRunId
              : page.items[0]?.run_id ?? null,
        );
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setError(message(cause));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Every card's 控制点 needs to know whether a HumanGate on this Run was
  // decided, and by whom -- data no field on `RunSnapshot` carries once the
  // Run has completed (see D2's `GET /v1/runs/{run_id}/human-gates`). Cards
  // data comes from the API, never from a hardcoded label keyed on run_id.
  useEffect(() => {
    if (!runs || !runs.length) return;
    let cancelled = false;
    setGateStates((current) => {
      const next = { ...current };
      for (const run of runs) {
        if (!(run.run_id in next)) next[run.run_id] = { status: "loading" };
      }
      return next;
    });
    void Promise.all(
      runs.map(async (run) => {
        try {
          const gates = await getRunHumanGates(run.run_id);
          return [run.run_id, { status: "loaded", gates }] as const;
        } catch {
          return [run.run_id, { status: "error" }] as const;
        }
      }),
    ).then((entries) => {
      if (cancelled) return;
      setGateStates((current) => {
        const next = { ...current };
        for (const [id, value] of entries) next[id] = value as GateFetchState;
        return next;
      });
    });
    return () => {
      cancelled = true;
    };
  }, [runs]);

  useEffect(() => {
    if (!selectedRunId) {
      setEvidenceState({ status: "idle" });
      return;
    }
    let cancelled = false;
    setEvidenceState({ status: "loading" });
    Promise.all([
      getEvents(selectedRunId),
      getToolInvocations(selectedRunId),
      getGuardrailDecisions(selectedRunId),
    ])
      .then(([events, tools, guardrails]) => {
        if (cancelled) return;
        setEvidenceState({
          status: "loaded",
          events: events as unknown as Record<string, unknown>[],
          tools,
          guardrails,
        });
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setEvidenceState({ status: "error", message: message(cause) });
      });
    return () => {
      cancelled = true;
    };
  }, [selectedRunId]);

  const selectedRun = runs?.find((run) => run.run_id === selectedRunId) ?? null;
  const selectedGates = selectedRunId ? gateStates[selectedRunId] : undefined;

  return (
    <section className="console-page demo-tour">
      <header className="demo-control-hero">
        <div className="demo-control-hero-copy">
          <span>GAIA CONTROL CENTER · 北辰 HR</span>
          <h1>一项 HR 请求，为什么被允许、等待或阻断？</h1>
          <p>业务工作台负责把事情办完；这里把同一次 Run 的模型、规则、人工审批和工具执行串成可核验的证据。</p>
        </div>
        <div className="demo-control-journey" aria-label="Gaia 演示路径">
          <a className="completed" href={SHOWCASE_URL}>
            <span>1</span><div><small>业务工作台</small><strong>发起 HR 请求</strong></div>
          </a>
          <ArrowRight size={17} />
          <div className="active">
            <span>2</span><div><small>Gaia 控制面</small><strong>解释与核验证据</strong></div>
          </div>
        </div>
      </header>
      <BusinessScenarioPicker />
      <div className="demo-experience-layout">
        <div className="demo-experience-primary">
          <div className="demo-column-heading">
            <span>01 · 选择 RUN</span>
            <h2>刚才发生了什么</h2>
            <p>选择一条 HR 业务运行，右侧会解释关键控制点，而不是只展示技术日志。</p>
          </div>
          {error && (
            <p className="console-notice" role="alert">
              {error}
            </p>
          )}
          {runs === null ? (
            <p className="empty-copy">正在加载运行...</p>
          ) : runs.length === 0 ? (
            <div className="demo-empty-state">
              <BriefcaseBusiness size={27} />
              <strong>还没有 HR 业务运行</strong>
              <p>先去业务工作台完成一次请假、入职权限开通或员工手册问答，Run 会自动出现在这里。</p>
              {SHOWCASE_UNAVAILABLE ? (
                <span className="link-unavailable" aria-disabled="true">HR 工作台本次未启动</span>
              ) : (
                <a className="primary-button" href={new URL("#onboarding", SHOWCASE_URL).toString()}>
                  去体验入职权限开通 <ArrowRight size={15} />
                </a>
              )}
            </div>
          ) : (
            <div className="demo-tour-grid">
              {runs.map((run) => (
                <DemoRunCard
                  key={run.run_id}
                  run={run}
                  gateState={gateStates[run.run_id]}
                  selected={run.run_id === selectedRunId}
                  onExplain={() => setSelectedRunId(run.run_id)}
                />
              ))}
            </div>
          )}
        </div>
        <aside className="demo-explanation-column" aria-live="polite">
          <div className="demo-column-heading">
            <span>02 · 理解结果</span>
            <h2>{selectedRun ? `${scenarioLabel(selectedRun.scenario_id)}为什么是这个结果` : "这次运行证明了什么"}</h2>
            <p>结论只来自运行记录、审批记录或策略决策；你仍可展开原始证据逐项核验。</p>
          </div>
          {!selectedRun ? (
            <div className="demo-explanation-empty">
              <Eye size={25} />
              <strong>完成一次业务操作后，这里会解释</strong>
              <ul><li>模型负责了什么</li><li>哪条规则做出决定</li><li>是否经过人工授权</li><li>工具最终有没有执行</li></ul>
            </div>
          ) : evidenceState.status === "idle" || evidenceState.status === "loading" ? (
            <p className="empty-copy">正在读取这次运行的解释...</p>
          ) : evidenceState.status === "error" ? (
            <p className="error-copy">{evidenceState.message}</p>
          ) : selectedGates?.status === "loading" || !selectedGates ? (
            <p className="empty-copy">正在核实人工审批记录...</p>
          ) : (
            <RunEvidence
              result={selectedRun}
              events={evidenceState.events}
              gates={Object.fromEntries(
                (selectedGates.status === "loaded" ? selectedGates.gates : []).map((gate) => [gate.gate_id, gate]),
              )}
              gateLoadIncomplete={selectedGates.status === "error"}
              toolObservability={evidenceState.tools}
              guardrailObservability={evidenceState.guardrails}
            />
          )}
        </aside>
      </div>
    </section>
  );
}

function BusinessScenarioPicker() {
  return (
    <section className="demo-scenario-picker">
      <div className="demo-scenario-heading">
        <div><span>业务入口</span><strong>换一个场景体验</strong></div>
        <p><ShieldCheck size={14} /> 三个场景都使用同一套 Gaia Runtime 与证据模型</p>
      </div>
      <div className="demo-scenario-grid">
        {SHOWCASE_EXAMPLES.map((example, index) =>
          SHOWCASE_UNAVAILABLE ? (
            <span className="demo-scenario-card link-unavailable" key={example.name}>
              <b>0{index + 1}</b><div><strong>{example.name}</strong><span>{example.description}</span></div>
              <em className="unavailable-badge">演示未启动</em>
            </span>
          ) : (
            <a
              className="demo-scenario-card"
              key={example.name}
              href={new URL(example.path, SHOWCASE_URL).toString()}
            >
              <b>0{index + 1}</b><div><strong>{example.name}</strong><span>{example.description}</span></div><ArrowRight size={16} />
            </a>
          ),
        )}
      </div>
    </section>
  );
}
