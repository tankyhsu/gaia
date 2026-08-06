import { expect, test } from "@playwright/test";

async function fixtureApi(page: import("@playwright/test").Page) {
  let projectApplied = false;
  await page.route("**/api/**", async (route) => {
    const { pathname } = new URL(route.request().url());
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (pathname.endsWith("/devtools/project/init/complete")) return json({ completed: true });
    if (pathname.endsWith("/devtools/project/init")) {
      if (route.request().method() === "POST") {
        projectApplied = true;
        return json({ applied: true, restart_required: true, starters: ["core-runtime"] });
      }
      return json({
        available: true,
        application_name: "gaia-demo",
        template_id: "knowledge",
        starters: ["core-runtime", "model-mock"],
        applied: projectApplied,
        templates: [
          { id: "knowledge", name: "基于企业知识回答", description: "检索企业文档并返回引用。", recommended_components: ["rag"], example: { name: "员工手册", description: "回答制度问题。", path: "/#handbook" } },
          { id: "approval", name: "连接并操作业务系统", description: "审批后再执行写操作。", recommended_components: [], example: { name: "入职权限开通", description: "IT 授权后写入 IAM。", path: "/#onboarding" } },
        ],
        components: [
          { id: "model", name: "外部模型", starter: "model-openai-compatible" },
          { id: "prompt-registry", name: "Prompt Registry", starter: "prompt-postgres" },
          { id: "rag", name: "知识检索", starter: "rag-postgres" },
          { id: "cache", name: "Redis 缓存", starter: "cache-redis" },
          { id: "outbox", name: "事务消息", starter: "outbox-postgres" },
        ],
      });
    }
    if (pathname.endsWith("/actuator/info")) return json({ application_name: "Gaia Demo", application_version: "0.1.0", framework_version: "0.1.0", profile: "dev", state: "started", config_hash: "2f8c4c9d", devtools_enabled: true });
    if (pathname.endsWith("/actuator/health")) return json({
      status: "UP",
      components: [
        { component_id: "model-default", required: true, health: { status: "configured", error_code: null } },
        { component_id: "workflow-default", required: true, health: { status: "configured", error_code: null } },
        { component_id: "context-default", required: true, health: { status: "configured", error_code: null } },
        { component_id: "persistence-default", required: true, health: { status: "configured", error_code: null } },
        { component_id: "policy-default", required: true, health: { status: "configured", error_code: null } },
        { component_id: "checkpoint-default", required: true, health: { status: "configured", error_code: null } },
        { component_id: "prompt-postgres", required: false, health: { status: "configured", error_code: null } },
      ],
    });
    if (pathname.endsWith("/actuator/components")) return json([
      { component_id: "model-default", kind: "model", implementation: "MockModel", status: "configured", starter_id: "model-mock" },
      { component_id: "workflow-default", kind: "workflow", implementation: "LangGraphWorkflow", status: "configured", starter_id: "workflow-langgraph" },
      { component_id: "context-default", kind: "context", implementation: "MockContext", status: "configured", starter_id: "context-mock" },
      { component_id: "persistence-default", kind: "persistence", implementation: "SqlitePersistence", status: "configured", starter_id: "core-runtime" },
      { component_id: "policy-default", kind: "policy", implementation: "ControlledPolicy", status: "configured", starter_id: "policy-controlled" },
      { component_id: "checkpoint-default", kind: "checkpoint", implementation: "SqliteCheckpoint", status: "configured", starter_id: "workflow-langgraph" },
      { component_id: "prompt-postgres", kind: "prompt", implementation: "PostgresPromptRegistry", status: "configured", starter_id: "prompt-postgres" },
      { component_id: "project-retriever", kind: "custom_retriever", implementation: "ProjectRetriever", status: "configured", starter_id: "project-starter" },
    ]);
    if (pathname.endsWith("/actuator/config")) return json({
      config_hash: "2f8c4c9d",
      config: {
        application: { name: "gaia-demo" },
        runtime: {
          environment: "mock",
          execution: {
            provider: "temporal",
            namespace: "gaia-dev-full",
            task_queue: "gaia-hr-dev-full",
            server_address: "temporal:7233",
          },
        },
        model: { provider: "mock" },
        workflow: { provider: "langgraph" },
        context: { provider: "mock" },
        policy: { provider: "controlled" },
        stores: {
          operational: { provider: "sqlite" },
          checkpoint: { provider: "sqlite" },
          memory: { provider: "disabled" },
          vector: { provider: "disabled" },
        },
        embedding: { provider: "disabled" },
        rag: { provider: "disabled" },
        cache: { provider: "disabled" },
        rate_limit: { provider: "disabled" },
        outbox: { provider: "disabled" },
        observability: { provider: "opentelemetry" },
        evaluation: { provider: "local" },
      },
      origins: {
        "application.name": "yaml",
        "runtime.environment": "profile",
        "model.provider": "starter_default",
        "workflow.provider": "starter_default",
        "context.provider": "default",
        "policy.provider": "yaml",
        "stores.operational.provider": "yaml",
        "stores.checkpoint.provider": "default",
        "stores.memory.provider": "default",
        "stores.vector.provider": "default",
        "embedding.provider": "default",
        "cache.provider": "default",
        "rate_limit.provider": "default",
        "outbox.provider": "default",
        "observability.provider": "yaml",
        "evaluation.provider": "yaml",
      },
    });
    if (pathname.endsWith("/actuator/runtime")) return json({
      window_hours: 24,
      generated_at: "2026-07-23T09:00:00Z",
      total_runs: 12,
      status_counts: { succeeded: 10, failed: 1, waiting_human: 1 },
      success_rate: 0.833,
      failure_rate: 0.083,
      blocked_rate: 0,
      run_duration: { average_ms: 820, p50_ms: 610, p95_ms: 1840 },
      pending_human_gates: 1,
      oldest_pending_gate_age_seconds: 92,
      human_gate_wait: { average_ms: 1200, p50_ms: 1200, p95_ms: 1200 },
      active_runs: 1,
      stale_runs: 0,
      error_counts: { MODEL_UNAVAILABLE: 1 },
      database: { backend: "sqlite", pool_class: "StaticPool", pool_size: null, checked_out: null, overflow: null, waiting_connections: null, lock_waiting_connections: null },
      outbox: { status_counts: {}, pending: 0, retrying: 0, dead_letter: 0 },
      issues: [],
    });
    // H2's recent-runs list: empty by default so it never introduces text
    // (status labels, run ids) that could collide with an unrelated test's
    // assertions elsewhere on the same 运行 page. The dedicated list test
    // below overrides this endpoint with a richer fixture of its own.
    if (pathname.endsWith("/v1/runs") && route.request().method() === "GET") {
      return json({ items: [], next_cursor: null });
    }
    if (pathname.endsWith("/v1/runs/run-001")) return json({
      run_id: "run-001",
      scenario_id: "employee.onboarding",
      mode: "mock",
      status: "waiting_human",
      user: { id: "hr-1", organization: "example", roles: ["operator"] },
      version_bundle: {
        policy: "onboarding:1",
        workflow: "onboarding:1",
        rules: "onboarding:1",
        prompt: "onboarding:1",
        model_profile: "mock",
        toolset: "onboarding:1",
        context_profile: "default",
      },
      pending_result: {
        employee_name: "李明",
        planned_systems: ["IAM", "邮箱", "项目空间"],
      },
      action_plan: {
        version: "1",
        current_action: 0,
        actions: [
          {
            step_id: "account",
            tool_name: "iam.create-account",
            risk_level: "medium",
            status: "waiting_human",
            depends_on: [],
            command_id: "command-001",
            gate_id: "gate-001",
            approval_view: {
              title: "创建员工主账号",
              summary: "为李明创建公司身份。",
              fields: { employee_id: "E-1042" },
              risk_explanation: "账号创建后将获得内部系统访问入口。",
            },
            result: null,
            error_code: null,
          },
        ],
      },
      handoff: null,
      continuation: {
        handler: "notify-requester",
        ready: false,
      },
      result: null,
      error: null,
      pending_gate_id: "gate-001",
      created_at: "2026-07-23T09:00:00Z",
      updated_at: "2026-07-23T09:00:01Z",
    });
    if (pathname.endsWith("/v1/runs/run-001/events")) return json([{
      event_id: "event-001",
      run_id: "run-001",
      sequence: 1,
      timestamp: "2026-07-22T09:00:00Z",
      actor: "system",
      step: "run.created",
      status: "succeeded",
      source_refs: [],
      rule_refs: [],
      error_code: null,
    }]);
    if (pathname.endsWith("/v1/runs/run-001/model-invocations")) return json({
      run_id: "run-001",
      summary: {
        total: 1,
        succeeded: 1,
        failed: 0,
        retry_count: 0,
        input_tokens: 42,
        output_tokens: 8,
        total_tokens: 50,
        estimated_cost_by_currency: {},
        duration: { average_ms: 320, p50_ms: 320, p95_ms: 320 },
      },
      invocations: [{
        invocation_id: "invocation-001",
        run_id: "run-001",
        scenario_id: "controlled-task",
        provider: "mock",
        model_id: "deterministic-mock",
        prompt_version: "controlled-task:1.0.0",
        prompt_content_hash: null,
        status: "succeeded",
        usage: {
          input_tokens: 42,
          output_tokens: 8,
          total_tokens: 50,
          estimated_cost: null,
          currency: null,
        },
        duration_ms: 320,
        first_token_latency_ms: null,
        retry_count: 0,
        error_code: null,
        started_at: "2026-07-23T09:00:00Z",
        completed_at: "2026-07-23T09:00:00.320Z",
      }],
    });
    if (pathname.endsWith("/v1/runs/run-001/tool-invocations")) return json({
      run_id: "run-001",
      summary: {
        total: 2,
        succeeded: 1,
        failed: 0,
        blocked: 1,
        timed_out: 0,
        duration: { average_ms: 18, p50_ms: 12, p95_ms: 24 },
      },
      invocations: [
        {
          invocation_id: "tool-001",
          run_id: "run-001",
          scenario_id: "employee.onboarding",
          tool_name: "hr.get-employee-profile",
          tool_version: "1.0.0",
          status: "succeeded",
          input_ref: "sha256:input",
          output_ref: "sha256:output",
          started_at: "2026-07-23T09:00:00Z",
          completed_at: "2026-07-23T09:00:00.012Z",
          duration_ms: 12,
          error_code: null,
        },
        {
          invocation_id: "tool-002",
          run_id: "run-001",
          scenario_id: "employee.onboarding",
          tool_name: "iam.lookup-sensitive-role",
          tool_version: "1.0.0",
          status: "blocked",
          input_ref: "sha256:input2",
          output_ref: null,
          started_at: "2026-07-23T09:00:00Z",
          completed_at: "2026-07-23T09:00:00.024Z",
          duration_ms: 24,
          error_code: "TOOL_ROLE_REQUIRED",
        },
      ],
    });
    if (pathname.endsWith("/v1/runs/run-001/guardrail-decisions")) return json({
      run_id: "run-001",
      summary: {
        total: 3,
        allowed: 1,
        rewritten: 1,
        blocked: 1,
        errors: 0,
        average_duration_ms: 7,
        by_stage: { input: 1, retrieval: 1, tool_input: 1 },
      },
      decisions: [
        {
          decision_id: "guardrail-001",
          run_id: "run-001",
          scenario_id: "controlled-task",
          stage: "input",
          guardrail_id: "pii-policy",
          guardrail_version: "1.2.0",
          status: "evaluated",
          action: "rewrite",
          risk_score: 0.84,
          input_ref: "sha256:input",
          output_ref: "sha256:output",
          code: "PII_REDACTED",
          started_at: "2026-07-23T09:00:00Z",
          completed_at: "2026-07-23T09:00:00.005Z",
          duration_ms: 5,
        },
        {
          decision_id: "guardrail-002",
          run_id: "run-001",
          scenario_id: "controlled-task",
          stage: "retrieval",
          guardrail_id: "context-policy",
          guardrail_version: "2.0.0",
          status: "evaluated",
          action: "allow",
          risk_score: 0.08,
          input_ref: "sha256:retrieval",
          output_ref: null,
          code: null,
          started_at: "2026-07-23T09:00:00.010Z",
          completed_at: "2026-07-23T09:00:00.014Z",
          duration_ms: 4,
        },
        {
          decision_id: "guardrail-003",
          run_id: "run-001",
          scenario_id: "controlled-task",
          stage: "tool_input",
          guardrail_id: "tool-policy",
          guardrail_version: "1.0.0",
          status: "evaluated",
          action: "block",
          risk_score: 1,
          input_ref: "sha256:tool",
          output_ref: null,
          code: "TOOL_SCOPE_BLOCKED",
          started_at: "2026-07-23T09:00:00.020Z",
          completed_at: "2026-07-23T09:00:00.032Z",
          duration_ms: 12,
        },
      ],
    });
    if (pathname.endsWith("/v1/human-gates/gate-001")) return json({
      gate_id: "gate-001",
      run_id: "run-001",
      command_id: "command-001",
      reason: "创建员工主账号需要 IT 确认。",
      risk_level: "medium",
      requested_action: { employee_id: "E-1042", internal_secret: "not-for-ui" },
      approval_view: {
        title: "创建员工主账号",
        summary: "为李明创建公司身份。",
        fields: { employee_id: "E-1042" },
        risk_explanation: "账号创建后将获得内部系统访问入口。",
      },
      status: "pending",
      requested_by: "hr-1",
      decided_by: null,
      comment: null,
      created_at: "2026-07-23T09:00:00Z",
      expires_at: "2026-07-24T09:00:00Z",
      decided_at: null,
    });
    if (pathname.includes("/v1/human-gates/gate-001/decision")) return json({ run_id: "run-001", status: "succeeded" });

    // --- Evidence tab fixtures -------------------------------------------------
    // run-evd-tight: an operator-tightened policy (`+ovr.<digest>` suffix) plus a
    // tool invocation that policy denied.
    if (pathname.endsWith("/v1/runs/run-evd-tight")) return json({
      run_id: "run-evd-tight",
      scenario_id: "employee.offboarding",
      mode: "customer",
      status: "blocked",
      user: { id: "hr-2", organization: "example", roles: ["operator"] },
      version_bundle: {
        policy: "offboarding:1.0.0+ovr.9c1d2f0a1b2c",
        workflow: "sha256:abc123def4560000",
        rules: "sha256:aaa111bbb2220000",
        prompt: "handwritten-v3",
        model_profile: "mock",
        toolset: "sha256:tool1234567890ab",
        context_profile: "default",
      },
      pending_result: null,
      action_plan: null,
      handoff: null,
      continuation: null,
      result: null,
      error: null,
      pending_gate_id: null,
      created_at: "2026-07-24T09:00:00Z",
      updated_at: "2026-07-24T09:00:01Z",
    });
    if (pathname.endsWith("/v1/runs/run-evd-tight/events")) return json([{
      event_id: "event-100",
      run_id: "run-evd-tight",
      sequence: 1,
      timestamp: "2026-07-24T09:00:00Z",
      actor: "system",
      step: "enforce_side_effect_policy",
      status: "failed",
      source_refs: [],
      rule_refs: [],
      error_code: "TOOL_DENIED_BY_POLICY",
    }]);
    if (pathname.endsWith("/v1/runs/run-evd-tight/model-invocations")) return json({
      run_id: "run-evd-tight",
      summary: { total: 0, succeeded: 0, failed: 0, retry_count: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0, estimated_cost_by_currency: {}, duration: { average_ms: null, p50_ms: null, p95_ms: null } },
      invocations: [],
    });
    if (pathname.endsWith("/v1/runs/run-evd-tight/tool-invocations")) return json({
      run_id: "run-evd-tight",
      summary: { total: 1, succeeded: 0, failed: 0, blocked: 1, timed_out: 0, duration: { average_ms: 9, p50_ms: 9, p95_ms: 9 } },
      invocations: [{
        invocation_id: "tool-100",
        run_id: "run-evd-tight",
        scenario_id: "employee.offboarding",
        tool_name: "hr.delete-account",
        tool_version: "1.0.0",
        status: "blocked",
        input_ref: "sha256:input-100",
        output_ref: null,
        started_at: "2026-07-24T09:00:00Z",
        completed_at: "2026-07-24T09:00:00.009Z",
        duration_ms: 9,
        error_code: "TOOL_DENIED_BY_POLICY",
      }],
    });
    if (pathname.endsWith("/v1/runs/run-evd-tight/guardrail-decisions")) return json({
      run_id: "run-evd-tight",
      summary: { total: 0, allowed: 0, rewritten: 0, blocked: 0, errors: 0, average_duration_ms: null, by_stage: {} },
      decisions: [],
    });

    // run-evd-clean: a plain (non-overridden) policy version, a version_bundle
    // missing the `context_profile` field, and nothing refused anywhere in the run.
    if (pathname.endsWith("/v1/runs/run-evd-clean")) return json({
      run_id: "run-evd-clean",
      scenario_id: "employee.onboarding",
      mode: "mock",
      status: "succeeded",
      user: { id: "hr-1", organization: "example", roles: ["operator"] },
      version_bundle: {
        policy: "onboarding:1.0.0",
        workflow: "sha256:def456abc1230000",
        rules: "sha256:bbb222aaa1110000",
        prompt: "sha256:promptfingerprint01",
        model_profile: "mock",
        toolset: "sha256:tool0987654321ba",
        // context_profile intentionally omitted to test that an absent
        // version_bundle field renders as absent, not as a fabricated value.
      },
      pending_result: null,
      action_plan: null,
      handoff: null,
      continuation: null,
      result: { status: "ok" },
      error: null,
      pending_gate_id: null,
      created_at: "2026-07-24T09:00:00Z",
      updated_at: "2026-07-24T09:00:02Z",
    });
    if (pathname.endsWith("/v1/runs/run-evd-clean/events")) return json([{
      event_id: "event-200",
      run_id: "run-evd-clean",
      sequence: 1,
      timestamp: "2026-07-24T09:00:00Z",
      actor: "system",
      step: "run.created",
      status: "succeeded",
      source_refs: [],
      rule_refs: [],
      error_code: null,
    }]);
    if (pathname.endsWith("/v1/runs/run-evd-clean/model-invocations")) return json({
      run_id: "run-evd-clean",
      summary: { total: 0, succeeded: 0, failed: 0, retry_count: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0, estimated_cost_by_currency: {}, duration: { average_ms: null, p50_ms: null, p95_ms: null } },
      invocations: [],
    });
    if (pathname.endsWith("/v1/runs/run-evd-clean/tool-invocations")) return json({
      run_id: "run-evd-clean",
      summary: { total: 1, succeeded: 1, failed: 0, blocked: 0, timed_out: 0, duration: { average_ms: 10, p50_ms: 10, p95_ms: 10 } },
      invocations: [{
        invocation_id: "tool-200",
        run_id: "run-evd-clean",
        scenario_id: "employee.onboarding",
        tool_name: "hr.get-employee-profile",
        tool_version: "1.0.0",
        status: "succeeded",
        input_ref: "sha256:input-200",
        output_ref: "sha256:output-200",
        started_at: "2026-07-24T09:00:00Z",
        completed_at: "2026-07-24T09:00:00.010Z",
        duration_ms: 10,
        error_code: null,
      }],
    });
    if (pathname.endsWith("/v1/runs/run-evd-clean/guardrail-decisions")) return json({
      run_id: "run-evd-clean",
      summary: { total: 1, allowed: 1, rewritten: 0, blocked: 0, errors: 0, average_duration_ms: 4, by_stage: { input: 1 } },
      decisions: [{
        decision_id: "guardrail-200",
        run_id: "run-evd-clean",
        scenario_id: "employee.onboarding",
        stage: "input",
        guardrail_id: "pii-policy",
        guardrail_version: "1.2.0",
        status: "evaluated",
        action: "allow",
        risk_score: 0.02,
        input_ref: "sha256:input-200",
        output_ref: null,
        code: null,
        started_at: "2026-07-24T09:00:00Z",
        completed_at: "2026-07-24T09:00:00.004Z",
        duration_ms: 4,
      }],
    });

    // run-evd-approved: an already-decided HumanGate, referenced from the
    // action plan's `gate_id`, so the approver comes from the gate record and
    // not from any field on the run itself.
    if (pathname.endsWith("/v1/runs/run-evd-approved")) return json({
      run_id: "run-evd-approved",
      scenario_id: "employee.offboarding",
      mode: "customer",
      status: "succeeded",
      user: { id: "hr-2", organization: "example", roles: ["operator"] },
      version_bundle: {
        policy: "offboarding:1.0.0",
        workflow: "sha256:abc123def4560000",
        rules: "sha256:aaa111bbb2220000",
        prompt: "sha256:promptfingerprint02",
        model_profile: "mock",
        toolset: "sha256:tool1234567890ab",
        context_profile: "default",
      },
      pending_result: null,
      action_plan: {
        version: "1",
        current_action: 1,
        actions: [{
          step_id: "revoke",
          tool_name: "iam.revoke-role",
          risk_level: "high",
          status: "succeeded",
          depends_on: [],
          command_id: "command-200",
          gate_id: "gate-002",
          approval_view: {
            title: "撤销高权限角色",
            summary: "撤销李明的管理员角色。",
            fields: { employee_id: "E-1042" },
            risk_explanation: "撤销后李明将立即失去后台管理权限。",
          },
          result: { revoked: true },
          error_code: null,
        }],
      },
      handoff: null,
      continuation: null,
      result: { status: "ok" },
      error: null,
      pending_gate_id: null,
      created_at: "2026-07-24T09:00:00Z",
      updated_at: "2026-07-24T09:00:05Z",
    });
    if (pathname.endsWith("/v1/runs/run-evd-approved/events")) return json([{
      event_id: "event-300",
      run_id: "run-evd-approved",
      sequence: 1,
      timestamp: "2026-07-24T09:00:00Z",
      actor: "system",
      step: "run.created",
      status: "succeeded",
      source_refs: [],
      rule_refs: [],
      error_code: null,
    }]);
    if (pathname.endsWith("/v1/runs/run-evd-approved/model-invocations")) return json({
      run_id: "run-evd-approved",
      summary: { total: 0, succeeded: 0, failed: 0, retry_count: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0, estimated_cost_by_currency: {}, duration: { average_ms: null, p50_ms: null, p95_ms: null } },
      invocations: [],
    });
    if (pathname.endsWith("/v1/runs/run-evd-approved/tool-invocations")) return json({
      run_id: "run-evd-approved",
      summary: { total: 0, succeeded: 0, failed: 0, blocked: 0, timed_out: 0, duration: { average_ms: null, p50_ms: null, p95_ms: null } },
      invocations: [],
    });
    if (pathname.endsWith("/v1/runs/run-evd-approved/guardrail-decisions")) return json({
      run_id: "run-evd-approved",
      summary: { total: 0, allowed: 0, rewritten: 0, blocked: 0, errors: 0, average_duration_ms: null, by_stage: {} },
      decisions: [],
    });
    if (pathname.endsWith("/v1/human-gates/gate-002")) return json({
      gate_id: "gate-002",
      run_id: "run-evd-approved",
      command_id: "command-200",
      reason: "撤销高权限角色需要二次确认。",
      risk_level: "high",
      requested_action: { employee_id: "E-1042" },
      approval_view: {
        title: "撤销高权限角色",
        summary: "撤销李明的管理员角色。",
        fields: { employee_id: "E-1042" },
        risk_explanation: "撤销后李明将立即失去后台管理权限。",
      },
      status: "approved",
      requested_by: "hr-2",
      decided_by: "ops-lead",
      comment: "已电话核实，予以撤销。",
      created_at: "2026-07-24T09:00:00Z",
      expires_at: "2026-07-25T09:00:00Z",
      decided_at: "2026-07-24T09:00:04Z",
    });
    // run-evd-bundle-approved: REGRESSION FIXTURE for the "affirmative lie"
    // defect. This is a *completed* run: `pending_gate_id` is already cleared
    // and there is no `action_plan`, exactly like every approved run looks
    // once it finishes. The only place the gate id survives is the
    // diagnostics bundle's `human_gates[]`. Before the fix, the Evidence tab
    // had no way to discover `gate-900` at all and asserted "从没有触发过人工
    // 确认" -- against a run whose event trail plainly shows one. This test
    // must fail against the pre-fix code.
    if (pathname.endsWith("/v1/runs/run-evd-bundle-approved")) return json({
      run_id: "run-evd-bundle-approved",
      scenario_id: "employee.offboarding",
      mode: "customer",
      status: "succeeded",
      user: { id: "hr-3", organization: "example", roles: ["operator"] },
      version_bundle: {
        policy: "offboarding:1.0.0",
        workflow: "sha256:abc123def4560000",
        rules: "sha256:aaa111bbb2220000",
        prompt: "sha256:promptfingerprint03",
        model_profile: "mock",
        toolset: "sha256:tool1234567890ab",
        context_profile: "default",
      },
      pending_result: null,
      action_plan: null,
      handoff: null,
      continuation: null,
      result: { status: "ok" },
      error: null,
      pending_gate_id: null,
      created_at: "2026-07-25T09:00:00Z",
      updated_at: "2026-07-25T09:00:05Z",
    });
    if (pathname.endsWith("/v1/runs/run-evd-bundle-approved/events")) return json([
      {
        event_id: "event-900",
        run_id: "run-evd-bundle-approved",
        sequence: 14,
        timestamp: "2026-07-25T09:00:02Z",
        actor: "system",
        step: "create_human_gate",
        status: "succeeded",
        source_refs: [],
        rule_refs: [],
        error_code: null,
      },
      {
        event_id: "event-901",
        run_id: "run-evd-bundle-approved",
        sequence: 15,
        timestamp: "2026-07-25T09:00:04Z",
        actor: "human",
        step: "human_gate_approved",
        status: "succeeded",
        source_refs: [],
        rule_refs: [],
        error_code: null,
      },
    ]);
    if (pathname.endsWith("/v1/runs/run-evd-bundle-approved/model-invocations")) return json({
      run_id: "run-evd-bundle-approved",
      summary: { total: 0, succeeded: 0, failed: 0, retry_count: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0, estimated_cost_by_currency: {}, duration: { average_ms: null, p50_ms: null, p95_ms: null } },
      invocations: [],
    });
    if (pathname.endsWith("/v1/runs/run-evd-bundle-approved/tool-invocations")) return json({
      run_id: "run-evd-bundle-approved",
      summary: { total: 0, succeeded: 0, failed: 0, blocked: 0, timed_out: 0, duration: { average_ms: null, p50_ms: null, p95_ms: null } },
      invocations: [],
    });
    if (pathname.endsWith("/v1/runs/run-evd-bundle-approved/guardrail-decisions")) return json({
      run_id: "run-evd-bundle-approved",
      summary: { total: 0, allowed: 0, rewritten: 0, blocked: 0, errors: 0, average_duration_ms: null, by_stage: {} },
      decisions: [],
    });
    if (pathname.endsWith("/v1/diagnostics/runs/run-evd-bundle-approved/bundle")) return json({
      schema_version: "1.0.0",
      run: { run_id: "run-evd-bundle-approved", status: "succeeded" },
      events: [],
      human_gates: [{
        gate_id: "gate-900",
        command_id: "command-900",
        status: "approved",
        risk_level: "high",
        approval_view: {
          title: "撤销高权限角色",
          summary: "撤销王芳的管理员角色。",
          fields: { employee_id: "E-2091" },
          risk_explanation: "撤销后王芳将立即失去后台管理权限。",
        },
        decided: true,
      }],
      side_effect_commands: [],
      redaction: { user_id: "sha256 pseudonym", request_text: "omitted", secrets: "omitted" },
    });
    if (pathname.endsWith("/v1/human-gates/gate-900")) return json({
      gate_id: "gate-900",
      run_id: "run-evd-bundle-approved",
      command_id: "command-900",
      reason: "撤销高权限角色需要二次确认。",
      risk_level: "high",
      requested_action: { employee_id: "E-2091" },
      approval_view: {
        title: "撤销高权限角色",
        summary: "撤销王芳的管理员角色。",
        fields: { employee_id: "E-2091" },
        risk_explanation: "撤销后王芳将立即失去后台管理权限。",
      },
      status: "approved",
      requested_by: "hr-3",
      decided_by: "night-ops-approver",
      comment: "已电话核实，予以撤销。",
      created_at: "2026-07-25T09:00:01Z",
      expires_at: "2026-07-26T09:00:01Z",
      decided_at: "2026-07-25T09:00:04Z",
    });

    // run-evd-gate-unloadable: the event trail shows human-gate activity and
    // the diagnostics bundle names a gate id, but fetching that gate's full
    // record fails (e.g. already pruned). The Evidence tab must say the
    // record could not be loaded -- never that no gate existed.
    if (pathname.endsWith("/v1/runs/run-evd-gate-unloadable")) return json({
      run_id: "run-evd-gate-unloadable",
      scenario_id: "employee.offboarding",
      mode: "customer",
      status: "succeeded",
      user: { id: "hr-4", organization: "example", roles: ["operator"] },
      version_bundle: {
        policy: "offboarding:1.0.0",
        workflow: "sha256:abc123def4560000",
        rules: "sha256:aaa111bbb2220000",
        prompt: "sha256:promptfingerprint04",
        model_profile: "mock",
        toolset: "sha256:tool1234567890ab",
        context_profile: "default",
      },
      pending_result: null,
      action_plan: null,
      handoff: null,
      continuation: null,
      result: { status: "ok" },
      error: null,
      pending_gate_id: null,
      created_at: "2026-07-25T10:00:00Z",
      updated_at: "2026-07-25T10:00:05Z",
    });
    if (pathname.endsWith("/v1/runs/run-evd-gate-unloadable/events")) return json([{
      event_id: "event-910",
      run_id: "run-evd-gate-unloadable",
      sequence: 9,
      timestamp: "2026-07-25T10:00:02Z",
      actor: "system",
      step: "create_human_gate",
      status: "succeeded",
      source_refs: [],
      rule_refs: [],
      error_code: null,
    }]);
    if (pathname.endsWith("/v1/runs/run-evd-gate-unloadable/model-invocations")) return json({
      run_id: "run-evd-gate-unloadable",
      summary: { total: 0, succeeded: 0, failed: 0, retry_count: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0, estimated_cost_by_currency: {}, duration: { average_ms: null, p50_ms: null, p95_ms: null } },
      invocations: [],
    });
    if (pathname.endsWith("/v1/runs/run-evd-gate-unloadable/tool-invocations")) return json({
      run_id: "run-evd-gate-unloadable",
      summary: { total: 0, succeeded: 0, failed: 0, blocked: 0, timed_out: 0, duration: { average_ms: null, p50_ms: null, p95_ms: null } },
      invocations: [],
    });
    if (pathname.endsWith("/v1/runs/run-evd-gate-unloadable/guardrail-decisions")) return json({
      run_id: "run-evd-gate-unloadable",
      summary: { total: 0, allowed: 0, rewritten: 0, blocked: 0, errors: 0, average_duration_ms: null, by_stage: {} },
      decisions: [],
    });
    if (pathname.endsWith("/v1/diagnostics/runs/run-evd-gate-unloadable/bundle")) return json({
      schema_version: "1.0.0",
      run: { run_id: "run-evd-gate-unloadable", status: "succeeded" },
      events: [],
      human_gates: [{
        gate_id: "gate-910",
        command_id: "command-910",
        status: "approved",
        risk_level: "high",
        approval_view: null,
        decided: true,
      }],
      side_effect_commands: [],
      redaction: { user_id: "sha256 pseudonym", request_text: "omitted", secrets: "omitted" },
    });
    if (pathname.endsWith("/v1/human-gates/gate-910")) return json({ code: "GATE_NOT_FOUND", message: "gate-910 has been pruned" }, 404);

    // run-evd-no-gate: nothing in the event trail, the run itself, or the
    // diagnostics bundle points at a HumanGate. This is the only shape that
    // may say "no human confirmation was ever triggered".
    if (pathname.endsWith("/v1/runs/run-evd-no-gate")) return json({
      run_id: "run-evd-no-gate",
      scenario_id: "employee.onboarding",
      mode: "mock",
      status: "succeeded",
      user: { id: "hr-5", organization: "example", roles: ["operator"] },
      version_bundle: {
        policy: "onboarding:1.0.0",
        workflow: "sha256:def456abc1230000",
        rules: "sha256:bbb222aaa1110000",
        prompt: "sha256:promptfingerprint05",
        model_profile: "mock",
        toolset: "sha256:tool0987654321ba",
        context_profile: "default",
      },
      pending_result: null,
      action_plan: null,
      handoff: null,
      continuation: null,
      result: { status: "ok" },
      error: null,
      pending_gate_id: null,
      created_at: "2026-07-25T11:00:00Z",
      updated_at: "2026-07-25T11:00:02Z",
    });
    if (pathname.endsWith("/v1/runs/run-evd-no-gate/events")) return json([{
      event_id: "event-920",
      run_id: "run-evd-no-gate",
      sequence: 1,
      timestamp: "2026-07-25T11:00:00Z",
      actor: "system",
      step: "run.created",
      status: "succeeded",
      source_refs: [],
      rule_refs: [],
      error_code: null,
    }]);
    if (pathname.endsWith("/v1/runs/run-evd-no-gate/model-invocations")) return json({
      run_id: "run-evd-no-gate",
      summary: { total: 0, succeeded: 0, failed: 0, retry_count: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0, estimated_cost_by_currency: {}, duration: { average_ms: null, p50_ms: null, p95_ms: null } },
      invocations: [],
    });
    if (pathname.endsWith("/v1/runs/run-evd-no-gate/tool-invocations")) return json({
      run_id: "run-evd-no-gate",
      summary: { total: 0, succeeded: 0, failed: 0, blocked: 0, timed_out: 0, duration: { average_ms: null, p50_ms: null, p95_ms: null } },
      invocations: [],
    });
    if (pathname.endsWith("/v1/runs/run-evd-no-gate/guardrail-decisions")) return json({
      run_id: "run-evd-no-gate",
      summary: { total: 0, allowed: 0, rewritten: 0, blocked: 0, errors: 0, average_duration_ms: null, by_stage: {} },
      decisions: [],
    });
    if (pathname.endsWith("/v1/diagnostics/runs/run-evd-no-gate/bundle")) return json({
      schema_version: "1.0.0",
      run: { run_id: "run-evd-no-gate", status: "succeeded" },
      events: [],
      human_gates: [],
      side_effect_commands: [],
      redaction: { user_id: "sha256 pseudonym", request_text: "omitted", secrets: "omitted" },
    });

    if (pathname.endsWith("/v1/evals/replays")) return json({
      replay_id: "replay-001",
      status: "completed",
      total: 3,
      passed: 3,
      failed: 0,
      created_at: "2026-07-23T09:00:00Z",
      finished_at: "2026-07-23T09:00:03Z",
      results: [
        { case_id: "case-a", passed: true, expected_status: "succeeded", actual_status: "succeeded" },
        { case_id: "case-b", passed: true, expected_status: "blocked", actual_status: "blocked" },
        { case_id: "case-c", passed: true, expected_status: "waiting_human", actual_status: "waiting_human" },
      ],
    }, 201);
    if (pathname.endsWith("/devtools/prompts/summary")) return json({
      prompt_id: "summary",
      versions: [
        {
          artifact: {
            prompt_id: "summary",
            version: "2.0.0",
            content_hash: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            input_schema: {},
            messages: [{ role: "system", content: "Summarize in three bullets." }],
            model_requirements: {},
            metadata: {},
          },
          status: "validating",
          validation: {
            passed: true,
            dataset_id: "summary-golden",
            dataset_version: "3",
            report_id: "report-2",
            gate_ids: ["pass-rate"],
          },
          created_by: "developer",
          created_at: "2026-07-23T08:00:00Z",
          updated_at: "2026-07-23T09:00:00Z",
        },
        {
          artifact: {
            prompt_id: "summary",
            version: "1.0.0",
            content_hash: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            input_schema: {},
            messages: [{ role: "system", content: "Summarize factually." }],
            model_requirements: {},
            metadata: {},
          },
          status: "published",
          validation: {
            passed: true,
            dataset_id: "summary-golden",
            dataset_version: "2",
            report_id: "report-1",
            gate_ids: ["pass-rate"],
          },
          created_by: "developer",
          created_at: "2026-07-22T08:00:00Z",
          updated_at: "2026-07-22T09:00:00Z",
        },
      ],
      releases: [
        {
          prompt_id: "summary",
          environment: "sandbox",
          version: "1.0.0",
          content_hash: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          updated_by: "release-manager",
          updated_at: "2026-07-22T09:00:00Z",
        },
      ],
    });
    if (pathname.endsWith("/devtools/prompts")) return json({
      provider: "postgres",
      access: "read_write",
      component_id: "prompt-postgres",
      root: null,
      artifacts: [],
    });
    return json({ code: "NOT_FOUND", message: pathname }, 404);
  });
}

test("quick start is skippable and overview remains the daily status page", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixtureApi(page);
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Gaia" })).toBeVisible();
  await expect(page.getByText("从一个接近你业务想法的场景开始", { exact: false })).toBeVisible();
  await expect(page.getByRole("heading", { name: "你想先解决哪一类业务问题？" })).toBeVisible();
  await expect(page.getByText("基于企业知识回答", { exact: true })).toBeVisible();
  await expect(page.getByText("处理文本和文档", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: /员工政策与个人假期问答/ })).toHaveAttribute(
    "href",
    /^http:\/\/(?:localhost|127\.0\.0\.1):4173\/#handbook$/,
  );
  await expect(page.getByRole("link", { name: /入职权限开通/ })).toHaveAttribute(
    "href",
    /^http:\/\/(?:localhost|127\.0\.0\.1):4173\/#onboarding$/,
  );
  await expect(page.getByRole("link", { name: /请假办理/ })).toHaveAttribute(
    "href",
    /^http:\/\/(?:localhost|127\.0\.0\.1):4173\/#leave$/,
  );
  await expect(page.getByRole("heading", { name: "从 Demo 开始，也保留安全边界" })).toBeVisible();
  await expect(page.getByText("运行 → 安全决策", { exact: false })).toBeVisible();
  await expect(page.getByRole("link", { name: "Gaia 文档" }).first()).toHaveAttribute(
    "href",
    /^http:\/\/(?:localhost|127\.0\.0\.1):4175\/$/,
  );
  await expect(page.getByText("uv run gaia starters", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "跳过引导" }).click();
  await expect(page.getByRole("heading", { name: "概览" })).toBeVisible();
  await expect(page.getByText("已验证", { exact: true })).toBeVisible();
  await expect(page.getByText("模型、流程、上下文、持久化和安全策略已装配")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("console-overview-desktop.png"), fullPage: true });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "概览" })).toBeVisible();
  await page.getByRole("button", { name: "快速开始", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Gaia" })).toBeVisible();
  await page.getByRole("button", { name: "组件", exact: true }).click();
  await expect(page.getByRole("cell", { name: "model-mock" })).toBeVisible();
  await expect(page.getByText("custom_retriever", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "场景", exact: true })).toHaveCount(0);
});

test("quick start applies a scenario template and optional components", async ({ page }, testInfo) => {
  await fixtureApi(page);
  await page.goto("/#quickstart");

  await page.screenshot({ path: testInfo.outputPath("quickstart-init-desktop.png"), fullPage: true });
  await page.getByText("连接并操作业务系统", { exact: true }).click();
  await page.getByText("调整组件", { exact: true }).click();
  await page.getByText("Redis 缓存", { exact: true }).click();
  await page.getByRole("button", { name: "生成场景并应用组件" }).click();

  await expect(page.getByText("场景和组件已经写入项目", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "完成并进入概览" }).click();
  await expect(page.getByRole("heading", { name: "概览" })).toBeVisible();
});

test("narrow Console keeps navigation compact and never widens the page", async ({ page }) => {
  await page.setViewportSize({ width: 700, height: 900 });
  await fixtureApi(page);
  await page.goto("/#quickstart");
  await expect(page.getByRole("heading", { name: "Gaia" })).toBeVisible();

  const layout = await page.evaluate(() => {
    const sidebar = document.querySelector<HTMLElement>(".console-sidebar");
    const top = document.querySelector<HTMLElement>(".console-top");
    if (!sidebar || !top) throw new Error("Console shell is missing");
    return {
      viewportWidth: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      sidebarHeight: sidebar.getBoundingClientRect().height,
      topHeight: top.getBoundingClientRect().height,
    };
  });

  expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth);
  expect(layout.sidebarHeight).toBeLessThan(150);
  expect(layout.topHeight).toBeLessThan(130);
  await expect(page.getByRole("button", { name: "演示", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "快速开始", exact: true })).toBeVisible();
});

test("effective configuration is read-only and explains field sources", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixtureApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "配置", exact: true }).click();
  await expect(page.getByRole("heading", { name: "当前生效配置" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Gaia 正在怎样连接外部能力" })).toBeVisible();
  await expect(page.getByText("Temporal 耐久执行", { exact: true })).toBeVisible();
  await expect(page.getByText("外部耐久编排", { exact: true })).toBeVisible();
  await expect(page.getByText("API 接收 Run", { exact: true })).toBeVisible();
  await expect(page.getByText("RAG 当前未启用", { exact: true })).toBeVisible();
  await expect(page.getByText("文档分块", { exact: true })).toBeVisible();
  await expect(page.getByText("gaia.yaml", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".config-form input:not([readonly])")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /保存|校验|激活|创建/ })).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "应用与场景" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "执行与治理" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "数据与基础设施" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "观测与评估" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "其他" })).toHaveCount(0);
  await page.getByRole("tab", { name: "模型与知识" }).click();
  await expect(page.getByRole("heading", { name: "大模型" })).toBeVisible();
  await expect(page.getByText("Starter 默认", { exact: true }).first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("console-config-desktop.png"), fullPage: true });
});

test("run gate events and replay views use API fixtures on mobile", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await fixtureApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Gaia" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("console-mobile-overview.png"), fullPage: true });
  await page.getByRole("button", { name: "运行", exact: true }).click();
  await page.getByLabel("Run ID").fill("run-001");
  await page.getByRole("heading", { name: "按 Run ID 查一条运行" }).locator("..").getByRole("button", { name: "查询" }).click();
  // The detail panel now opens on 证据; this assertion is about the 结果 panel.
  await page.getByRole("tab", { name: "结果" }).click();
  await expect(page.getByText("等待动作结果 · notify-requester")).toBeVisible();
  await page.getByRole("tab", { name: "事件链" }).click();
  await expect(page.getByText("run.created")).toBeVisible();
  await page.getByRole("tab", { name: "模型调用" }).click();
  await expect(page.getByRole("heading", { name: "模型调用" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "deterministic-mock" })).toBeVisible();
  await page.getByRole("tab", { name: "工具调用" }).click();
  await expect(page.getByRole("heading", { name: "工具调用" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "hr.get-employee-profile" })).toBeVisible();
  await expect(page.getByText("TOOL_ROLE_REQUIRED", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "安全决策" }).click();
  await expect(page.getByRole("heading", { name: "安全决策" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "模型输入" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "已阻断" })).toBeVisible();
  await expect(page.getByText("PII_REDACTED", { exact: true })).toBeVisible();
  await page.getByLabel("Gate ID").fill("gate-001");
  await page.getByRole("heading", { name: "处理一条人工审批" }).locator("..").getByRole("button", { name: "查询" }).click();
  await expect(page.getByText("等待处理")).toBeVisible();
  await expect(page.getByRole("heading", { name: "创建员工主账号" })).toBeVisible();
  // Deciding is only offered once the gate has been loaded and shown to be
  // pending: approving a high-risk write without having seen it is not an
  // approval, and the buttons used to enable on a non-empty text box alone.
  await expect(page.getByRole("button", { name: "批准这条请求" })).toBeVisible();
  await expect(page.getByText("internal_secret")).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("console-mobile-operations.png"), fullPage: true });
  await page.getByRole("button", { name: "测试" }).click();
  await page.getByRole("button", { name: "运行测试" }).click();
  await expect(page.getByText("replay-001")).toBeVisible();
  await expect(page.getByText("100.0%")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("console-mobile.png"), fullPage: true });
});

// H2: the 运行 view must be browsable without already holding a Run ID.
// Before this, seeing anything required pasting a UUID obtained from a curl
// response. This asserts the list renders enough per row to choose one (a
// scenario, a status, whether it went through human approval, and a
// timestamp) for every shape `humanApprovalLabel` distinguishes, and that
// clicking a row opens that exact run's detail panel already on 证据 --
// the same landing tab the by-ID lookup uses.
test("recent runs list renders from a fixture and opens a row's detail on the 证据 tab", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixtureApi(page);
  // Overrides fixtureApi's empty default for this test only (Playwright runs
  // the most-recently-registered matching route first). Four rows exercise
  // every "人工确认" label `humanApprovalLabel` derives from `RunSnapshot`
  // fields: waiting, approved, none, and rejected. `run-001` and
  // `run-evd-approved` also have full per-run detail fixtures above, so
  // clicking either row can be asserted through to the 证据 tab.
  await page.route("**/api/v1/runs", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            run_id: "run-001",
            scenario_id: "employee.onboarding",
            mode: "mock",
            status: "waiting_human",
            user: { id: "hr-1", organization: "example", roles: ["operator"] },
            version_bundle: {
              policy: "onboarding:1", workflow: "onboarding:1", rules: "onboarding:1",
              prompt: "onboarding:1", model_profile: "mock", toolset: "onboarding:1", context_profile: "default",
            },
            pending_result: { employee_name: "李明", planned_systems: ["IAM", "邮箱", "项目空间"] },
            action_plan: null,
            handoff: null,
            continuation: { handler: "notify-requester", ready: false },
            result: null,
            error: null,
            pending_gate_id: "gate-001",
            created_at: "2026-07-23T09:00:00Z",
            updated_at: "2026-07-23T09:00:01Z",
          },
          {
            run_id: "run-evd-approved",
            scenario_id: "employee.offboarding",
            mode: "customer",
            status: "succeeded",
            user: { id: "hr-2", organization: "example", roles: ["operator"] },
            version_bundle: {
              policy: "offboarding:1.0.0", workflow: "sha256:abc123def4560000", rules: "sha256:aaa111bbb2220000",
              prompt: "sha256:promptfingerprint02", model_profile: "mock", toolset: "sha256:tool1234567890ab", context_profile: "default",
            },
            pending_result: null,
            action_plan: {
              version: "1",
              current_action: 1,
              actions: [{
                step_id: "revoke", tool_name: "iam.revoke-role", risk_level: "high", status: "succeeded",
                depends_on: [], command_id: "command-200", gate_id: "gate-002",
                approval_view: null, result: { revoked: true }, error_code: null,
              }],
            },
            handoff: null,
            continuation: null,
            result: { status: "ok" },
            error: null,
            pending_gate_id: null,
            created_at: "2026-07-24T09:00:00Z",
            updated_at: "2026-07-24T09:00:05Z",
          },
          {
            run_id: "run-evd-tight",
            scenario_id: "employee.offboarding",
            mode: "customer",
            status: "blocked",
            user: { id: "hr-2", organization: "example", roles: ["operator"] },
            version_bundle: {
              policy: "offboarding:1.0.0+ovr.9c1d2f0a1b2c", workflow: "sha256:abc123def4560000", rules: "sha256:aaa111bbb2220000",
              prompt: "handwritten-v3", model_profile: "mock", toolset: "sha256:tool1234567890ab", context_profile: "default",
            },
            pending_result: null,
            action_plan: null,
            handoff: null,
            continuation: null,
            result: null,
            error: null,
            pending_gate_id: null,
            created_at: "2026-07-24T09:00:00Z",
            updated_at: "2026-07-24T09:00:01Z",
          },
          {
            run_id: "run-list-rejected",
            scenario_id: "employee.offboarding",
            mode: "customer",
            status: "blocked",
            user: { id: "hr-3", organization: "example", roles: ["operator"] },
            version_bundle: {
              policy: "offboarding:1.0.0", workflow: "sha256:abc123def4560000", rules: "sha256:aaa111bbb2220000",
              prompt: "sha256:promptfingerprint09", model_profile: "mock", toolset: "sha256:tool1234567890ab", context_profile: "default",
            },
            pending_result: null,
            action_plan: {
              version: "1",
              current_action: 0,
              actions: [{
                step_id: "revoke", tool_name: "iam.revoke-role", risk_level: "high", status: "failed",
                depends_on: [], command_id: "command-300", gate_id: "gate-300",
                approval_view: null, result: null, error_code: "HUMAN_GATE_REJECTED",
              }],
            },
            handoff: null,
            continuation: null,
            result: null,
            error: {
              code: "HUMAN_GATE_REJECTED", message: "The human gate was rejected.", category: "policy",
              retryable: false, operator_action: "Review the rejection reason.", trace_id: "trace-300",
            },
            pending_gate_id: null,
            created_at: "2026-07-26T09:00:00Z",
            updated_at: "2026-07-26T09:00:03Z",
          },
        ],
        next_cursor: null,
      }),
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "运行", exact: true }).click();

  await expect(page.getByText("查看 Gaia 执行了什么、哪些 Run 需要介入")).toBeVisible();
  await expect(page.getByRole("heading", { name: "待处理 Run" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "最近运行" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Run 详情" })).toBeVisible();
  await expect(page.getByText("还没有选择 Run")).toBeVisible();

  // Rows are located by the run id in the cell's `title`, not by its visible
  // text: the table now shows a shortened id so a 40-character hex string
  // stops filling the column. The full value stays in the DOM.
  const waitingRow = page
    .locator(".run-list-table tbody tr")
    .filter({ has: page.locator(`[title="run-001"]`) });
  await expect(waitingRow).toBeVisible();
  await expect(waitingRow.getByText("等待人工确认", { exact: true })).toBeVisible();
  await expect(waitingRow.getByText("等待中", { exact: true })).toBeVisible();
  await expect(waitingRow.getByRole("button", { name: "查看详情" })).toBeVisible();

  const approvedRow = page
    .locator(".run-list-table tbody tr")
    .filter({ has: page.locator(`[title="run-evd-approved"]`) });
  await expect(approvedRow.getByText("已完成", { exact: true })).toBeVisible();
  await expect(approvedRow.getByText("已通过", { exact: true })).toBeVisible();

  // Nothing on this run's snapshot claims a gate happened, but nothing rules
  // it out either (no `action_plan`, matching how `examples/controlled_task`
  // shaped runs look once complete) -- so the row must not claim "no gate"
  // with more confidence than the data supports.
  const noGateRow = page
    .locator(".run-list-table tbody tr")
    .filter({ has: page.locator(`[title="run-evd-tight"]`) });
  await expect(noGateRow.getByText("未记录", { exact: true })).toBeVisible();

  const rejectedRow = page
    .locator(".run-list-table tbody tr")
    .filter({ has: page.locator(`[title="run-list-rejected"]`) });
  await expect(rejectedRow.getByText("被拒绝", { exact: true })).toBeVisible();

  // Loading more is a single button, not pagination controls -- and this
  // fixture's page has no `next_cursor`, so it must not appear at all.
  await expect(page.getByRole("button", { name: "加载更多" })).toHaveCount(0);

  await page.screenshot({ path: testInfo.outputPath("console-recent-runs-list.png"), fullPage: true });

  await approvedRow.getByRole("button", { name: "查看详情" }).click();

  // Landed on 证据 without an extra click, exactly like the by-ID lookup.
  await expect(approvedRow.getByRole("button", { name: "正在查看" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "人工审批", exact: true })).toBeVisible();
  await expect(page.getByText("ops-lead").first()).toBeVisible();
  await expect(page.getByRole("tab", { name: "证据" })).toHaveAttribute("aria-selected", "true");
  await page.screenshot({ path: testInfo.outputPath("console-recent-runs-detail.png"), fullPage: true });

  // The by-ID lookup box still works and stays independent of the list.
  await expect(page.getByLabel("Run ID")).toHaveValue("run-evd-approved");
});

test("observability groups Gaia signals integrations and component visibility", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixtureApi(page);
  await page.goto("/");

  await expect(page.getByRole("navigation", { name: "运行与诊断" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "构建与治理" })).toBeVisible();
  await page.getByRole("button", { name: "可观测", exact: true }).click();

  await expect(page.getByRole("heading", { name: "可观测", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "运行信号" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "观测链路" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Gaia 运行证据" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "OpenTelemetry 导出" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Langfuse" })).toBeVisible();
  await expect(page.getByText("页面确认配置已装配", { exact: false })).toHaveCount(0);
  await expect(page.getByText("Gaia 本地证据仍完整可查", { exact: false })).toBeVisible();
  await expect(page.getByRole("heading", { name: "观测覆盖" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "组件可见性" })).toBeVisible();

  await page.getByRole("button", { name: "查看 Run 与证据" }).click();
  await expect(page.getByRole("heading", { name: "最近运行" })).toBeVisible();
});

test("prompt workspace keeps versions releases and import in separate tabs", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixtureApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Prompt", exact: true }).click();
  await page.getByRole("button", { name: "查询", exact: true }).click();

  await expect(page.getByRole("heading", { name: "Prompt Registry" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "2.0.0" })).toBeVisible();
  await expect(page.getByText("summary-golden · 3")).toBeVisible();
  await page.getByRole("tab", { name: "环境指针" }).click();
  await expect(page.getByRole("cell", { name: "sandbox" })).toBeVisible();
  await page.getByRole("tab", { name: "导入 Draft" }).click();
  await expect(page.getByLabel("Prompt Artifact JSON")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("console-prompt-workspace.png"), fullPage: true });
});

test("prompt navigation remains visible when no provider is configured", async ({ page }, testInfo) => {
  await fixtureApi(page);
  await page.route("**/api/devtools/prompts", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        provider: "disabled",
        access: "unavailable",
        component_id: null,
        root: null,
        artifacts: [],
      }),
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Prompt", exact: true }).click();

  await expect(page.getByRole("heading", { name: "Prompt", exact: true })).toBeVisible();
  await expect(page.getByText("当前应用没有装配 Prompt Provider。")).toBeVisible();
  await expect(page.getByRole("cell", { name: "文件 Prompt" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Prompt Registry" })).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("console-prompt-disabled.png"),
    fullPage: true,
  });
});

test("evidence tab calls out an operator policy override and lists a denied tool invocation", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixtureApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "运行", exact: true }).click();
  await page.getByLabel("Run ID").fill("run-evd-tight");
  await page.getByRole("heading", { name: "按 Run ID 查一条运行" }).locator("..").getByRole("button", { name: "查询" }).click();
  await page.getByRole("tab", { name: "证据" }).click();

  await expect(page.getByRole("heading", { name: "依据哪版策略" })).toBeVisible();
  await expect(page.getByText("被运维通过", { exact: false })).toBeVisible();
  await expect(page.getByText("apply_policy_override", { exact: false })).toBeVisible();

  // 内容指纹 is now a collapsed conclusion ("N of 6 derived from content")
  // rather than six rows the reader has to parse. The per-field honesty it
  // guarantees is unchanged -- it is one disclosure away, and asserted below.
  await page.getByText("内容指纹：", { exact: false }).click();
  await expect(page.getByText("9c1d2f0a1b2c", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("由内容本身推导出的指纹", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("手填版本号，不是内容指纹", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("handwritten-v3")).toBeVisible();

  await expect(page.getByRole("heading", { name: "什么被拒了" })).toBeVisible();
  await expect(page.getByText("hr.delete-account", { exact: false })).toBeVisible();
  await expect(page.getByText("TOOL_DENIED_BY_POLICY", { exact: false }).first()).toBeVisible();

  await expect(page.getByText("这个 Run 没有触发过人工确认")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("console-evidence-tight.png"), fullPage: true });
});

test("evidence tab treats a plain policy as unmodified, shows an absent version field honestly, and states nothing was refused", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixtureApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "运行", exact: true }).click();
  await page.getByLabel("Run ID").fill("run-evd-clean");
  await page.getByRole("heading", { name: "按 Run ID 查一条运行" }).locator("..").getByRole("button", { name: "查询" }).click();
  await page.getByRole("tab", { name: "证据" }).click();

  await expect(page.getByText("1.0.0", { exact: true })).toBeVisible();
  await expect(page.getByText("被运维通过", { exact: false })).toHaveCount(0);
  await expect(page.getByText("没有被运维从配置", { exact: false })).toBeVisible();

  // context_profile was omitted from the fixture's version_bundle -- it must
  // render as explicitly absent, never as a plausible-looking default.
  // 内容指纹 is now a collapsed conclusion ("N of 6 derived from content")
  // rather than six rows the reader has to parse. The per-field honesty it
  // guarantees is unchanged -- it is one disclosure away, and asserted below.
  await page.getByText("内容指纹：", { exact: false }).click();
  await expect(page.getByText("未记录").first()).toBeVisible();

  await expect(page.getByText("这个 Run 里没有任何调用被拒绝")).toBeVisible();
  await expect(page.getByText("这个 Run 没有触发过人工确认")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("console-evidence-clean.png"), fullPage: true });
});

test("evidence tab attributes an approval to the gate's decided_by as the authenticated identity", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixtureApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "运行", exact: true }).click();
  await page.getByLabel("Run ID").fill("run-evd-approved");
  await page.getByRole("heading", { name: "按 Run ID 查一条运行" }).locator("..").getByRole("button", { name: "查询" }).click();
  await page.getByRole("tab", { name: "证据" }).click();

  // The approver is now named twice on purpose: once in the plain-language
  // summary at the top, and once in the gate record it is derived from.
  await expect(page.getByRole("heading", { name: "发生了什么", exact: true })).toBeVisible();
  await expect(page.getByText("ops-lead 批准了它", { exact: false })).toBeVisible();
  await expect(page.getByRole("heading", { name: "人工审批", exact: true })).toBeVisible();
  await expect(page.getByText("ops-lead")).toHaveCount(2);
  await expect(page.getByText("来自服务端认证结果", { exact: false })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("console-evidence-approved.png"), fullPage: true });
});

// Regression test for the "affirmative lie" defect (H0): a *completed* run
// has `pending_gate_id: null` and no `action_plan`, exactly like every
// approved run looks once it finishes -- the only surviving gate id lives in
// the diagnostics bundle's `human_gates[]`. Before the fix, the Evidence tab
// had no way to discover `gate-900` and rendered "这个 Run 没有触发过人工确认"
// against a run whose event trail plainly shows `create_human_gate` ->
// `human_gate_approved`. This test must fail against the pre-fix code (see
// the manual regression check documented alongside this change).
test("evidence tab discovers a decided gate from the diagnostics bundle on a completed run with no pending_gate_id or action_plan", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixtureApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "运行", exact: true }).click();
  await page.getByLabel("Run ID").fill("run-evd-bundle-approved");
  await page.getByRole("heading", { name: "按 Run ID 查一条运行" }).locator("..").getByRole("button", { name: "查询" }).click();
  await page.getByRole("tab", { name: "证据" }).click();

  await expect(page.getByRole("heading", { name: "人工审批", exact: true })).toBeVisible();
  await expect(page.getByText("night-ops-approver").first()).toBeVisible();
  await expect(page.getByText("来自服务端认证结果", { exact: false })).toBeVisible();
  await expect(page.getByText("这个 Run 没有触发过人工确认")).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("console-evidence-bundle-approved.png"), fullPage: true });
});

// Second of the three required states: the event trail shows human-gate
// activity and the diagnostics bundle names a gate id, but fetching that
// gate's full record fails (already pruned). The panel must say the record
// could not be loaded, and must NOT say no gate ever existed -- collapsing
// this into the "no gate" state is the exact bug this card is about.
test("evidence tab reports an unloadable gate record as unverified, never as no gate having existed", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixtureApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "运行", exact: true }).click();
  await page.getByLabel("Run ID").fill("run-evd-gate-unloadable");
  await page.getByRole("heading", { name: "按 Run ID 查一条运行" }).locator("..").getByRole("button", { name: "查询" }).click();
  await page.getByRole("tab", { name: "证据" }).click();

  await expect(page.getByRole("heading", { name: "人工审批", exact: true })).toBeVisible();
  await expect(page.getByText("记录无法读取", { exact: false })).toBeVisible();
  await expect(page.getByText("这不代表没有发生过人工确认", { exact: false })).toBeVisible();
  await expect(page.getByText("这个 Run 没有触发过人工确认")).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("console-evidence-gate-unloadable.png"), fullPage: true });
});

// Third state: no gate activity anywhere -- not in the events, not in the
// run, not in the diagnostics bundle. This is the only shape allowed to say
// "no human confirmation was ever triggered".
test("evidence tab says no human confirmation was triggered only when there is no gate activity anywhere", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixtureApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "运行", exact: true }).click();
  await page.getByLabel("Run ID").fill("run-evd-no-gate");
  await page.getByRole("heading", { name: "按 Run ID 查一条运行" }).locator("..").getByRole("button", { name: "查询" }).click();
  await page.getByRole("tab", { name: "证据" }).click();

  await expect(page.getByRole("heading", { name: "人工审批", exact: true })).toBeVisible();
  await expect(page.getByText("这个 Run 没有触发过人工确认")).toBeVisible();
  await expect(page.getByText("记录无法读取", { exact: false })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("console-evidence-no-gate.png"), fullPage: true });
});

// The demo landing page is the control half of the HR journey: business entry
// points first, then real Run outcomes and an evidence-backed explanation.
// Run data comes from the API, never from a hardcoded result label.
function demoRun(overrides: Record<string, unknown>): Record<string, unknown> {
  return {
    scenario_id: "hr.leave.request",
    mode: "mock",
    version_bundle: {
      policy: "policy-controlled-task:1.0.0", workflow: "1.0.0", rules: "1.0.0",
      prompt: "1.0.0", model_profile: "1.0.0", toolset: "1.0.0", context_profile: "1.0.0",
    },
    pending_result: null,
    action_plan: null,
    handoff: null,
    continuation: null,
    pending_gate_id: null,
    created_at: "2026-07-30T09:00:00Z",
    updated_at: "2026-07-30T09:00:05Z",
    ...overrides,
  };
}

const DEMO_APPROVED_RUN = demoRun({
  run_id: "demo-run-approved",
  status: "succeeded",
  user: { id: "demo-operator", organization: "org-alpha", roles: ["operator"] },
  result: { status: "ok" },
  error: null,
});
const DEMO_HUMAN_REJECTED_RUN = demoRun({
  run_id: "demo-run-human-rejected",
  status: "blocked",
  user: { id: "demo-operator", organization: "org-alpha", roles: ["operator"] },
  result: null,
  error: {
    code: "HUMAN_GATE_REJECTED", message: "The pending action was rejected by an approver.",
    category: "policy", retryable: false, operator_action: "Review the decision comment.",
    trace_id: "trace-demo-2",
  },
});
const DEMO_POLICY_BLOCKED_RUN = demoRun({
  run_id: "demo-run-policy-blocked",
  status: "blocked",
  user: { id: "demo-reader", organization: "org-alpha", roles: ["reader"] },
  result: null,
  error: {
    code: "FORBIDDEN", message: "The caller does not have permission to perform this action.",
    category: "authorization", retryable: false, operator_action: "Check the caller identity.",
    trace_id: "trace-demo-3",
  },
});
const DEMO_RUNS = [DEMO_POLICY_BLOCKED_RUN, DEMO_HUMAN_REJECTED_RUN, DEMO_APPROVED_RUN];

function demoGate(overrides: Record<string, unknown>): Record<string, unknown> {
  return {
    command_id: "command-demo",
    reason: "Publishing changes a durable business record.",
    risk_level: "high",
    requested_action: { resource_id: "res-001" },
    approval_view: null,
    requested_by: "demo-operator",
    comment: null,
    created_at: "2026-07-30T09:00:00Z",
    expires_at: "2026-07-31T09:00:00Z",
    ...overrides,
  };
}

async function fixtureDemoRuns(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/runs", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: DEMO_RUNS, next_cursor: null }),
    });
  });

  const emptyObservability = (runId: string) => ({
    run_id: runId,
    summary: {
      total: 0, succeeded: 0, failed: 0, retry_count: 0, input_tokens: 0, output_tokens: 0,
      total_tokens: 0, estimated_cost_by_currency: {}, duration: { average_ms: null, p50_ms: null, p95_ms: null },
    },
    invocations: [],
  });
  const emptyGuardrails = (runId: string) => ({
    run_id: runId,
    summary: { total: 0, allowed: 0, rewritten: 0, blocked: 0, errors: 0, average_duration_ms: null, by_stage: {} },
    decisions: [],
  });
  const gatesByRun: Record<string, unknown[]> = {
    "demo-run-approved": [
      demoGate({
        gate_id: "demo-gate-approved",
        run_id: "demo-run-approved",
        status: "approved",
        decided_by: "demo-approver",
        decided_at: "2026-07-30T09:00:04Z",
      }),
    ],
    "demo-run-human-rejected": [
      demoGate({
        gate_id: "demo-gate-rejected",
        run_id: "demo-run-human-rejected",
        status: "rejected",
        decided_by: "demo-approver",
        decided_at: "2026-07-30T09:00:04Z",
      }),
    ],
    "demo-run-policy-blocked": [],
  };

  for (const run of DEMO_RUNS) {
    const runId = run.run_id as string;
    await page.route(`**/api/v1/runs/${runId}`, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(run) }),
    );
    await page.route(`**/api/v1/runs/${runId}/events`, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
    await page.route(`**/api/v1/runs/${runId}/model-invocations`, (route) =>
      route.fulfill({
        status: 200, contentType: "application/json", body: JSON.stringify(emptyObservability(runId)),
      }),
    );
    await page.route(`**/api/v1/runs/${runId}/tool-invocations`, (route) =>
      route.fulfill({
        status: 200, contentType: "application/json", body: JSON.stringify(emptyObservability(runId)),
      }),
    );
    await page.route(`**/api/v1/runs/${runId}/guardrail-decisions`, (route) =>
      route.fulfill({
        status: 200, contentType: "application/json", body: JSON.stringify(emptyGuardrails(runId)),
      }),
    );
    await page.route(`**/api/v1/runs/${runId}/human-gates`, (route) =>
      route.fulfill({
        status: 200, contentType: "application/json", body: JSON.stringify(gatesByRun[runId]),
      }),
    );
  }
}

test("demo connects HR business entry points to the control evidence view", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixtureApi(page);
  await fixtureDemoRuns(page);
  await page.goto("/#demo");

  await expect(page.getByRole("heading", { name: "一项 HR 请求，为什么被允许、等待或阻断？" })).toBeVisible();
  await expect(page.getByText("业务工作台", { exact: true })).toBeVisible();
  await expect(page.getByText("Gaia 控制面", { exact: true })).toBeVisible();
  await expect(page.locator(".demo-scenario-card")).toHaveCount(3);
  await expect(page.locator('.demo-scenario-card[href$="#onboarding"]')).toBeVisible();
  await expect(page.getByRole("heading", { name: "运行", exact: true })).toHaveCount(0);

  const cards = page.locator(".demo-run-card");
  await expect(cards).toHaveCount(3);
  await expect(cards.getByText("请假申请", { exact: true })).toHaveCount(3);

  const approvedCard = cards.filter({ hasText: "已完成" });
  await expect(approvedCard).toBeVisible();
  await expect(approvedCard.getByText("demo-approver 批准", { exact: false })).toBeVisible();

  const humanRejectedCard = cards.filter({ hasText: "被人工拒绝" });
  await expect(humanRejectedCard).toBeVisible();
  await expect(humanRejectedCard.getByText("demo-approver 拒绝", { exact: false })).toBeVisible();

  const policyBlockedCard = cards.filter({ hasText: "被策略拒绝" });
  await expect(policyBlockedCard).toBeVisible();
  await expect(policyBlockedCard.getByText("策略校验 · 发起者没有执行该操作的权限", { exact: true })).toBeVisible();
  await expect(policyBlockedCard.getByText("代码 FORBIDDEN", { exact: true })).toBeVisible();

  // Never the "control working correctly" defect this page exists to fix:
  // a blocked-by-design Run must never be called a failure.
  await expect(page.getByText("失败", { exact: true })).toHaveCount(0);

  await page.screenshot({ path: testInfo.outputPath("console-demo-tour.png"), fullPage: true });
});

test("demo keeps the selected run and its explanation together in two columns", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixtureApi(page);
  await fixtureDemoRuns(page);
  await page.goto("/#demo");

  const approvedCard = page.locator(".demo-run-card").filter({ hasText: "已完成" });
  await approvedCard.getByRole("button", { name: "查看解释" }).click();

  await expect(page).toHaveURL(/#demo$/);
  await expect(page.getByRole("heading", { name: "请假申请为什么是这个结果" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "成功率" })).toHaveCount(0);
  await expect(page.getByText("需要处理")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "发生了什么", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "人工审批", exact: true })).toBeVisible();
  await expect(page.getByText("业务操作员", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("demo-operator", { exact: true })).toBeVisible();
  await expect(page.getByText("demo-approver").first()).toBeVisible();
  await expect(page.getByText("hr.leave.request", { exact: true })).toBeVisible();

  const rejectedCard = page.locator(".demo-run-card").filter({ hasText: "被人工拒绝" });
  await rejectedCard.getByRole("button", { name: "查看解释" }).click();

  await expect(page).toHaveURL(/#demo$/);
  await expect(page.getByRole("heading", { name: "人工审批", exact: true })).toBeVisible();
  await expect(page.getByText("demo-approver").first()).toBeVisible();
});

test("demo deep link selects the Run created in the HR workspace", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixtureApi(page);
  await fixtureDemoRuns(page);
  await page.goto("/?run=demo-run-approved#demo");

  const selected = page.locator(".demo-run-card.selected");
  await expect(selected).toContainText("已完成");
  await expect(page.getByRole("heading", { name: "请假申请为什么是这个结果" })).toBeVisible();
  await expect(page).toHaveURL(/\?run=demo-run-approved#demo$/);
});
