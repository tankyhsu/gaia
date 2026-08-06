import type { GuardrailDecision } from "./types";

const SCENARIO_LABELS: Record<string, string> = {
  "hr.leave.request": "请假申请",
  "hr.onboarding.access": "入职权限开通",
  "hr.handbook.answer": "员工手册问答",
  "employee.offboarding": "员工离职办理",
};

export function scenarioLabel(scenarioId: string): string {
  return SCENARIO_LABELS[scenarioId] ?? "业务流程";
}

export function guardrailStageLabel(stage: GuardrailDecision["stage"]): string {
  return {
    input: "模型输入",
    retrieval: "知识检索",
    output: "模型输出",
    tool_input: "操作参数",
    tool_output: "操作结果",
  }[stage];
}

// Runtime step names are stable identifiers the Workflow writes into the event
// stream; they are what an auditor greps for. These labels exist so a reader
// who is not the author can follow the trail -- they never replace the raw
// name, which stays visible on hover and in the expanded trail.
const STEP_LABELS: Record<string, string> = {
  receive_request: "收到请求",
  validate_request: "校验准入",
  start_workflow: "开始执行",
  interpret_intent: "理解意图",
  read_resource: "读取数据",
  authorize_context: "校验上下文权限",
  load_context: "载入上下文",
  retrieve_knowledge: "检索知识",
  propose_side_effect: "提出写入请求",
  enforce_side_effect_policy: "校验写入策略",
  enforce_budget: "校验预算",
  create_human_gate: "创建人工审批",
  human_gate_approved: "人工批准",
  human_gate_rejected: "人工拒绝",
  human_gate_expired: "审批超时",
  execute_side_effect: "执行写入",
  command_result: "写入结果",
  resume_continuation: "恢复执行",
  agent_handoff: "转交 Agent",
  run_scenario_activity: "场景执行",
  cancel_run: "取消运行",
  finalize: "收尾",
};

export function stepLabel(step: string): string | null {
  return STEP_LABELS[step] ?? null;
}

// The steps a reader is actually looking for: where a control acted, and where
// the run ended. Everything else is ordinary progress and starts collapsed.
const DECISIVE_STEPS = new Set([
  "validate_request",
  "propose_side_effect",
  "enforce_side_effect_policy",
  "enforce_budget",
  "create_human_gate",
  "human_gate_approved",
  "human_gate_rejected",
  "human_gate_expired",
  "execute_side_effect",
  "command_result",
  "cancel_run",
]);

export function isDecisiveStep(step: string, status: string): boolean {
  // A step that blocked or failed is decisive whatever its name -- that is
  // precisely the step the reader came to find.
  return DECISIVE_STEPS.has(step) || status === "blocked" || status === "failed";
}
