import type {
  HumanGate,
  ReplaySnapshot,
  PromptArtifact,
  PromptRelease,
  PromptVersion,
  PromptWorkspaceStatus,
  PromptWorkspaceSnapshot,
  ProjectInitSnapshot,
  RunEvent,
  RunGuardrailObservability,
  RunModelObservability,
  RunSnapshot,
  RuntimeSummary,
} from "./types";

interface ErrorBody {
  detail?: string;
  message?: string;
  code?: string;
  operator_action?: string;
  trace_id?: string;
  details?: { reason?: string };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
  const contentType = response.headers.get("content-type") || "";
  const rawBody = await response.text();
  let body: ErrorBody | T | undefined;
  if (contentType.includes("application/json") && rawBody) {
    try {
      body = JSON.parse(rawBody) as ErrorBody | T;
    } catch {
      body = undefined;
    }
  }
  if (!response.ok) {
    const errorBody = body as ErrorBody | undefined;
    const gatewaySummary = response.status === 502 || response.status === 503
      ? "Gaia 应用暂时不可达，请确认应用已经启动后重试"
      : `请求失败（HTTP ${response.status}）`;
    const summary = errorBody?.message
      || errorBody?.detail
      || errorBody?.details?.reason
      || errorBody?.code
      || gatewaySummary;
    const action = errorBody?.operator_action ? `处理建议：${errorBody.operator_action}` : "";
    const trace = errorBody?.trace_id ? `Trace ID：${errorBody.trace_id}` : "";
    throw new Error([summary, action, trace].filter(Boolean).join(" "));
  }
  if (body === undefined) {
    throw new Error("Gaia 应用返回了无法识别的响应");
  }
  return body as T;
}

export function getRun(runId: string): Promise<RunSnapshot> {
  return request(`/v1/runs/${encodeURIComponent(runId)}`);
}

export function getEvents(runId: string): Promise<RunEvent[]> {
  return request(`/v1/runs/${encodeURIComponent(runId)}/events`);
}

export function getModelInvocations(runId: string): Promise<RunModelObservability> {
  return request(`/v1/runs/${encodeURIComponent(runId)}/model-invocations`);
}

export function getGuardrailDecisions(
  runId: string,
): Promise<RunGuardrailObservability> {
  return request(`/v1/runs/${encodeURIComponent(runId)}/guardrail-decisions`);
}

export function getGate(gateId: string): Promise<HumanGate> {
  return request(`/v1/human-gates/${encodeURIComponent(gateId)}`);
}

export function decideGate(gateId: string, decision: "approved" | "rejected") {
  return request<RunSnapshot>(`/v1/human-gates/${encodeURIComponent(gateId)}/decision`, {
    method: "POST",
    body: JSON.stringify({
      decision,
      decided_by: "ops-approver",
      roles: ["approver"],
      comment: decision === "approved" ? "现场确认通过" : "现场确认拒绝",
    }),
  });
}

export function runReplay(): Promise<ReplaySnapshot> {
  return request("/v1/evals/replays", {
    method: "POST",
    body: JSON.stringify({ all: true }),
  });
}

export function runtimeSummary(): Promise<RuntimeSummary> {
  return request("/actuator/runtime?window_hours=24&stale_after_seconds=300");
}

export function actuator<T>(name: string): Promise<T> { return request(`/actuator/${name}`); }

export function inspectPrompt(promptId: string): Promise<PromptWorkspaceSnapshot> {
  return request(`/devtools/prompts/${encodeURIComponent(promptId)}`);
}

export function inspectPromptWorkspace(): Promise<PromptWorkspaceStatus> {
  return request("/devtools/prompts");
}

export function importPrompt(
  artifact: Omit<PromptArtifact, "content_hash"> & { content_hash?: string },
): Promise<PromptVersion> {
  return request("/devtools/prompts/import", {
    method: "POST",
    headers: { "X-Gaia-Actor": "dev-console" },
    body: JSON.stringify(artifact),
  });
}

export function publishPrompt(
  promptId: string,
  version: string,
  environment: PromptRelease["environment"],
): Promise<PromptRelease> {
  return request(
    `/devtools/prompts/${encodeURIComponent(promptId)}/${encodeURIComponent(version)}/publish`,
    {
      method: "POST",
      headers: { "X-Gaia-Actor": "dev-console" },
      body: JSON.stringify({ environment }),
    },
  );
}

export function rollbackPrompt(
  promptId: string,
  targetVersion: string,
  environment: PromptRelease["environment"],
): Promise<PromptRelease> {
  return request(`/devtools/prompts/${encodeURIComponent(promptId)}/rollback`, {
    method: "POST",
    headers: { "X-Gaia-Actor": "dev-console" },
    body: JSON.stringify({ environment, target_version: targetVersion }),
  });
}

export function inspectProjectInit(): Promise<ProjectInitSnapshot> {
  return request("/devtools/project/init");
}

export function applyProjectInit(templateId: string, components: string[]) {
  return request<{
    applied: boolean;
    restart_required: boolean;
    starters: string[];
  }>("/devtools/project/init", {
    method: "POST",
    body: JSON.stringify({ template_id: templateId, components }),
  });
}

export function completeProjectInit() {
  return request<{ completed: boolean }>("/devtools/project/init/complete", {
    method: "POST",
  });
}
