export type RunStatus =
  | "received"
  | "validated"
  | "running"
  | "waiting_human"
  | "degraded"
  | "blocked"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface UserIdentity {
  id: string;
  organization: string;
  roles: string[];
}

export interface RunSnapshot {
  run_id: string;
  scenario_id: string;
  mode: "mock" | "sandbox" | "customer";
  status: RunStatus;
  user: UserIdentity;
  version_bundle: Record<string, string>;
  result: Record<string, unknown> | null;
  error: {
    code: string;
    message: string;
    category: string;
    retryable: boolean;
    operator_action: string;
    trace_id: string;
  } | null;
  pending_gate_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface RunEvent {
  event_id: string;
  sequence: number;
  timestamp: string;
  actor: string;
  step: string;
  status: string;
  source_refs: string[];
  rule_refs: string[];
  error_code: string | null;
}

export interface HumanGate {
  gate_id: string;
  run_id: string;
  reason: string;
  risk_level: string;
  requested_action: Record<string, unknown>;
  status: string;
  requested_by: string;
  created_at: string;
  expires_at: string;
}

export interface ReplaySnapshot {
  replay_id: string;
  status: string;
  total: number;
  passed: number;
  failed: number;
  results: Array<{ case_id: string; passed: boolean; actual_status: string }>;
}

export interface DurationSummary {
  average_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
}

export interface RuntimeIssue {
  run_id: string;
  scenario_id: string;
  status: string;
  bottleneck: string;
  age_seconds: number;
  error_code: string | null;
  updated_at: string;
}

export interface RuntimeSummary {
  window_hours: number;
  stale_after_seconds: number;
  generated_at: string;
  total_runs: number;
  status_counts: Record<string, number>;
  success_rate: number;
  failure_rate: number;
  blocked_rate: number;
  active_runs: number;
  stale_runs: number;
  pending_human_gates: number;
  oldest_pending_gate_age_seconds: number | null;
  run_duration: DurationSummary;
  human_gate_wait: DurationSummary;
  error_counts: Record<string, number>;
  database: {
    backend: string;
    pool_class: string;
    pool_size: number | null;
    checked_out: number | null;
    overflow: number | null;
    waiting_connections: number | null;
    lock_waiting_connections: number | null;
  };
  outbox: {
    status_counts: Record<string, number>;
    pending: number;
    retrying: number;
    dead_letter: number;
  };
  issues: RuntimeIssue[];
}

export interface PromptArtifact {
  prompt_id: string;
  version: string;
  content_hash: string;
  input_schema: Record<string, unknown>;
  messages: Array<{ role: string; content: string }>;
  model_requirements: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface PromptVersion {
  artifact: PromptArtifact;
  status: "draft" | "validating" | "published" | "retired";
  validation: {
    passed: boolean;
    dataset_id: string;
    dataset_version: string;
    report_id: string;
    gate_ids: string[];
  } | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface PromptRelease {
  prompt_id: string;
  environment: "mock" | "sandbox" | "customer";
  version: string;
  content_hash: string;
  updated_by: string;
  updated_at: string;
}

export interface PromptWorkspaceSnapshot {
  prompt_id: string;
  versions: PromptVersion[];
  releases: PromptRelease[];
}

export interface PromptWorkspaceStatus {
  provider: "disabled" | "file" | "postgres";
  access: "unavailable" | "read_only" | "read_write";
  component_id: string | null;
  root: string | null;
  artifacts: Array<{
    prompt_id: string;
    version: string;
    content_hash: string;
    relative_path: string;
  }>;
}

export interface ModelInvocation {
  invocation_id: string;
  run_id: string;
  scenario_id: string;
  provider: string;
  model_id: string;
  prompt_version: string;
  prompt_content_hash: string | null;
  status: "succeeded" | "failed";
  usage: {
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    estimated_cost: number | null;
    currency: string | null;
  } | null;
  duration_ms: number;
  first_token_latency_ms: number | null;
  retry_count: number;
  error_code: string | null;
  started_at: string;
  completed_at: string;
}

export interface RunModelObservability {
  run_id: string;
  summary: {
    total: number;
    succeeded: number;
    failed: number;
    retry_count: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    estimated_cost_by_currency: Record<string, number>;
    duration: DurationSummary;
  };
  invocations: ModelInvocation[];
}

export interface GuardrailDecision {
  decision_id: string;
  run_id: string;
  scenario_id: string;
  stage: "input" | "retrieval" | "output" | "tool_input" | "tool_output";
  guardrail_id: string;
  guardrail_version: string;
  status: "evaluated" | "error";
  action: "allow" | "rewrite" | "block";
  risk_score: number | null;
  input_ref: string;
  output_ref: string | null;
  code: string | null;
  started_at: string;
  completed_at: string;
  duration_ms: number;
}

export interface RunGuardrailObservability {
  run_id: string;
  summary: {
    total: number;
    allowed: number;
    rewritten: number;
    blocked: number;
    errors: number;
    average_duration_ms: number | null;
    by_stage: Record<string, number>;
  };
  decisions: GuardrailDecision[];
}

export interface ProjectInitSnapshot {
  available: boolean;
  application_name: string;
  template_id: string;
  starters: string[];
  applied: boolean;
  templates: Array<{
    id: string;
    name: string;
    description: string;
    recommended_components: string[];
  }>;
  components: Array<{
    id: string;
    name: string;
    starter: string;
  }>;
}
