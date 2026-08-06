import { useState } from "react";

import { Identifier, Metric, displayValue } from "./StructuredView";
import { guardrailStageLabel, isDecisiveStep, scenarioLabel, stepLabel } from "./labels";
import type {
  HumanGate,
  RunGuardrailObservability,
  RunSnapshot,
  RunToolObservability,
} from "./types";

type State = Record<string, unknown>;

const CONTENT_FINGERPRINT_FIELDS: ReadonlyArray<[string, string]> = [
  ["workflow", "工作流"],
  ["rules", "业务规则"],
  ["prompt", "Prompt"],
  ["model_profile", "模型档案"],
  ["toolset", "工具集"],
  ["context_profile", "上下文档案"],
];

interface ParsedPolicyVersion {
  policyId: string;
  version: string;
  overrideDigest: string | null;
}

// `version_bundle.policy` is assembled by `freeze_version_bundle` as
// `f"{policy.policy_id}:{policy.version}"`. When an operator has tightened the
// policy from `gaia.yaml`, `apply_policy_override` appends `f"+ovr.{digest}"`
// -- and only ever when something actually changed relative to the baseline
// (see `src/gaia/runtime/policy.py`). Absence of the suffix is therefore itself
// evidence: this run's policy was not tightened by a config override.
export function parsePolicyVersion(
  raw: string | undefined | null,
): ParsedPolicyVersion | null {
  if (!raw) return null;
  const separator = raw.lastIndexOf(":");
  if (separator <= 0) return null;
  const policyId = raw.slice(0, separator);
  const rest = raw.slice(separator + 1);
  const override = rest.indexOf("+ovr.");
  if (override < 0) return { policyId, version: rest, overrideDigest: null };
  return {
    policyId,
    version: rest.slice(0, override),
    overrideDigest: rest.slice(override + "+ovr.".length) || null,
  };
}

const GATE_STEPS = new Set([
  "create_human_gate",
  "human_gate_approved",
  "human_gate_rejected",
  "human_gate_expired",
]);

export function hasGateActivity(events: State[]): boolean {
  return events.some((event) => GATE_STEPS.has(String(event.step ?? "")));
}

function hasStep(events: State[], step: string): boolean {
  return events.some((event) => String(event.step ?? "") === step);
}

const ROLE_LABELS: Record<string, string> = {
  hr: "HR 运营人员",
  employee: "员工",
  operator: "业务操作员",
  reader: "只读用户",
  approver: "审批人",
};

const ERROR_LABELS: Record<string, string> = {
  ACCESS_POLICY_VIOLATION: "权限草案超出岗位模板",
  HUMAN_GATE_REJECTED: "人工审批拒绝了请求",
  HUMAN_GATE_EXPIRED: "人工审批已超时",
  FORBIDDEN: "发起者没有执行该操作的权限",
};

export function roleLabel(roles: string[]): string {
  return roles.map((role) => ROLE_LABELS[role] ?? role).join("、") || "未知身份";
}

export function errorLabel(code: string | undefined | null): string {
  if (!code) return "运行被控制机制终止";
  return ERROR_LABELS[code] ?? "运行被控制机制终止";
}

function resultMessage(result: RunSnapshot): string | null {
  const value = result.result;
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const message = (value as State).message;
  return typeof message === "string" && message.trim() ? message : null;
}

/**
 * The sentences a reader gets before any identifier or version number.
 *
 * Every line is derived from something actually present in the run's own
 * record. A stage that cannot be resolved produces no sentence rather than a
 * plausible one -- an evidence page that fills its gaps by inference is the
 * failure this page exists to prevent.
 */
export function narrative(
  result: RunSnapshot,
  events: State[],
  gates: HumanGate[],
): string[] {
  const lines: string[] = [];
  lines.push(`${roleLabel(result.user?.roles ?? [])}发起了${scenarioLabel(result.scenario_id)}。`);

  if (hasStep(events, "propose_side_effect")) {
    lines.push("场景提出了一次会改动外部系统的写入请求，运行时没有直接执行它。");
  }

  const gate = gates.find((entry) => entry.status !== "pending") ?? gates[0];
  if (gate) {
    if (gate.status === "approved" && gate.decided_by) {
      lines.push(`写入被暂停等待人工审批，${gate.decided_by} 批准了它。`);
    } else if (gate.status === "rejected" && gate.decided_by) {
      lines.push(`写入被暂停等待人工审批，${gate.decided_by} 拒绝了它，写入没有发生。`);
    } else if (gate.status === "expired") {
      lines.push("写入被暂停等待人工审批，审批在超时前没有结论，写入没有发生。");
    } else if (gate.status === "pending") {
      lines.push("写入正在等待人工审批，还没有人做出决定。");
    }
  } else if (hasGateActivity(events)) {
    lines.push("这次运行触发过人工审批，但审批记录当前读不到——不能据此判断它有没有被批准。");
  }

  if (hasStep(events, "execute_side_effect")) {
    lines.push("批准之后，写入才交由运行时执行。");
  }

  if (result.status === "succeeded") {
    lines.push("运行成功结束。");
  } else if (result.status === "blocked") {
    lines.push(resultMessage(result) ?? `${errorLabel(result.error?.code)}，运行没有继续执行。`);
  } else if (result.status === "failed") {
    lines.push(`运行失败${result.error?.code ? `：${result.error.code}` : ""}。`);
  } else if (result.status === "cancelled") {
    lines.push("运行被取消。");
  }

  return lines;
}

function StateTrail({ events }: { events: State[] }) {
  const [expanded, setExpanded] = useState(false);
  if (!events.length) return <p className="empty-copy">没有可展示的事件。</p>;

  const shown = expanded
    ? events
    : events.filter((event) =>
        isDecisiveStep(String(event.step ?? ""), String(event.status ?? "")),
      );
  const hidden = events.length - shown.length;

  return (
    <>
      <ol className="evidence-trail">
        {shown.map((event) => {
          const step = String(event.step ?? "event");
          const label = stepLabel(step);
          return (
            <li className="evidence-trail-step" key={String(event.sequence ?? event.event_id)}>
              <span className="evidence-trail-name" title={step}>
                {label ?? step}
              </span>
              <span className="evidence-trail-status">{displayValue(event.status)}</span>
              {label ? <code className="evidence-trail-raw">{step}</code> : null}
            </li>
          );
        })}
      </ol>
      {hidden > 0 || expanded ? (
        <button type="button" className="secondary-button" onClick={() => setExpanded(!expanded)}>
          {expanded ? "只看关键步骤" : `展开其余 ${hidden} 个步骤`}
        </button>
      ) : null}
    </>
  );
}

export function RunEvidence({
  result,
  events,
  gates,
  gateLoadIncomplete,
  toolObservability,
  guardrailObservability,
}: {
  result: RunSnapshot;
  events: State[];
  gates: Record<string, HumanGate>;
  gateLoadIncomplete: boolean;
  toolObservability: RunToolObservability;
  guardrailObservability: RunGuardrailObservability;
}) {
  const bundle = result.version_bundle ?? {};
  const policy = parsePolicyVersion(bundle.policy);
  const deniedTools = toolObservability.invocations.filter((item) => item.status === "blocked");
  const blockedGuardrails = guardrailObservability.decisions.filter(
    (item) => item.action === "block",
  );
  const hasRefusal =
    deniedTools.length > 0 || blockedGuardrails.length > 0 || Boolean(result.error);
  const gateList = Object.values(gates);
  // Three distinct states, never collapsed into each other: gates were found
  // and can be shown; the run shows gate activity (or a known gate id failed to
  // load) but no record is available; or there is no evidence of a gate at all.
  // Only the last may say "this run never went through approval".
  const gateEvidenceIncomplete =
    !gateList.length && (gateLoadIncomplete || hasGateActivity(events));
  const fingerprinted = CONTENT_FINGERPRINT_FIELDS.filter(([key]) =>
    String(bundle[key] ?? "").startsWith("sha256:"),
  ).length;

  return (
    <div className="evidence-panel">
      <section className="evidence-section evidence-summary">
        <h3>发生了什么</h3>
        <ol className="evidence-narrative">
          {narrative(result, events, gateList).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ol>
        <dl className="evidence-technical-facts">
          <div>
            <dt>业务场景</dt>
            <dd><strong>{scenarioLabel(result.scenario_id)}</strong><code>{result.scenario_id}</code></dd>
          </div>
          <div>
            <dt>发起身份</dt>
            <dd><strong>{roleLabel(result.user?.roles ?? [])}</strong><code>{result.user?.id ?? "未记录"}</code></dd>
          </div>
          <div>
            <dt>控制结果</dt>
            <dd><strong>{result.status === "blocked" ? errorLabel(result.error?.code) : displayValue(result.status)}</strong><code>{result.error?.code ?? result.status}</code></dd>
          </div>
        </dl>
      </section>

      <section className="evidence-section">
        <h3>人工审批</h3>
        {gateList.length ? (
          gateList.map((entry) => (
            <div className="evidence-gate" key={entry.gate_id}>
              <div className="summary-grid compact-summary">
                <Identifier label="Gate" value={entry.gate_id} />
                <Metric label="状态" value={displayValue(entry.status)} />
                <Metric label="决定人" value={entry.decided_by ?? "未记录"} />
                <Metric label="决定时间" value={displayValue(entry.decided_at)} />
              </div>
              {entry.decided_by ? (
                <p className="evidence-note">
                  这个身份来自服务端认证结果，不是请求体里客户端自称的字段。
                </p>
              ) : (
                <p className="empty-copy">这个 Gate 还没有被处置，没有批准人。</p>
              )}
            </div>
          ))
        ) : gateEvidenceIncomplete ? (
          <p className="evidence-callout">
            这个 Run 的事件轨迹里出现过人工确认相关的步骤（如 <code>create_human_gate</code>
            或 <code>human_gate_approved</code>），但对应的 Gate 记录无法读取——可能已被清理，
            也可能是诊断接口暂时不可用。<strong>这不代表没有发生过人工确认</strong>，只是这次
            查不到批准人是谁；请勿据此断言该 Run 未经审批。
          </p>
        ) : (
          <p className="empty-copy">这个 Run 没有触发过人工确认（HumanGate）。</p>
        )}
      </section>

      <section className="evidence-section">
        <h3>什么被拒了</h3>
        {hasRefusal ? (
          <>
            {deniedTools.length ? (
              <div>
                <h4>被拒绝的工具调用</h4>
                <ul>
                  {deniedTools.map((item) => (
                    <li key={item.invocation_id}>
                      {item.tool_name} · {item.error_code ?? "-"}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {blockedGuardrails.length ? (
              <div>
                <h4>被阻断的安全决策</h4>
                <ul>
                  {blockedGuardrails.map((item) => (
                    <li key={item.decision_id}>
                      {guardrailStageLabel(item.stage)} · {item.guardrail_id} · {item.code ?? "-"}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {result.error ? (
              <div>
                <h4>终态错误</h4>
                <p>
                  {result.error.code} · {result.error.message}
                </p>
              </div>
            ) : null}
          </>
        ) : (
          <p className="empty-copy">这个 Run 里没有任何调用被拒绝。</p>
        )}
      </section>

      <section className="evidence-section">
        <h3>依据哪版策略</h3>
        {policy ? (
          <>
            <div className="summary-grid compact-summary">
              <Identifier label="策略 ID" value={policy.policyId} />
              <Metric label="策略版本" value={policy.version} />
              <Metric label="运维收紧" value={policy.overrideDigest ? "是" : "否"} />
            </div>
            {policy.overrideDigest ? (
              <p className="evidence-callout">
                这个场景的策略被运维通过 <code>gaia.yaml</code> 的配置收紧过：指纹{" "}
                <code>{policy.overrideDigest}</code> 标识的是具体哪一次收紧。覆盖只能让策略
                变得更严格（更严的写入模式、更小的预算、更少的工具），任何放宽策略的覆盖在
                启动期就会被拒绝——见 <code>src/gaia/runtime/policy.py</code> 的{" "}
                <code>apply_policy_override</code>。
              </p>
            ) : (
              <p className="evidence-note">
                策略版本号里没有 <code>+ovr.</code> 后缀，说明这次运行用的是没有被运维从配置
                收紧过的原始策略。
              </p>
            )}
            <details className="evidence-details">
              <summary>
                内容指纹：{CONTENT_FINGERPRINT_FIELDS.length} 项中 {fingerprinted} 项由内容推导
              </summary>
              <div className="structured-view">
                {CONTENT_FINGERPRINT_FIELDS.map(([key, label]) => {
                  const value = bundle[key];
                  const isFingerprint =
                    typeof value === "string" && value.startsWith("sha256:");
                  return (
                    <div className="structured-field" key={key}>
                      <span>{label}</span>
                      {value ? (
                        <strong>
                          {value}
                          <span className="table-secondary">
                            {isFingerprint
                              ? "由内容本身推导出的指纹，不会和它命名的内容不一致"
                              : "手填版本号，不是内容指纹"}
                          </span>
                        </strong>
                      ) : (
                        <strong>未记录</strong>
                      )}
                    </div>
                  );
                })}
              </div>
            </details>
          </>
        ) : (
          <p className="empty-copy">未记录策略版本。</p>
        )}
      </section>

      <section className="evidence-section">
        <h3>状态轨迹</h3>
        <StateTrail events={events} />
        <p className="evidence-note">
          这条轨迹取自 Temporal Workflow History，并由 Gaia 投影进自己的审计库，因此
          Temporal 的保留期过后仍然查得到。改动 Workflow 会不会让已经在飞的运行对不上，
          由 <code>tests/integration/test_workflow_replay.py</code> 的历史回放在 CI 里拦住。
        </p>
      </section>
    </div>
  );
}
