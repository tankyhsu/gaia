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
        template_id: "basic",
        starters: ["core-runtime", "model-mock"],
        applied: projectApplied,
        templates: [
          { id: "basic", name: "处理文本和文档", description: "总结、分类、信息抽取和内容生成。", recommended_components: [] },
          { id: "knowledge", name: "基于企业知识回答", description: "检索企业文档并返回引用。", recommended_components: ["rag"] },
          { id: "approval", name: "连接并操作业务系统", description: "审批后再执行写操作。", recommended_components: [] },
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
        runtime: { environment: "mock" },
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
        cache: { provider: "disabled" },
        rate_limit: { provider: "disabled" },
        outbox: { provider: "disabled" },
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
    if (pathname.endsWith("/v1/runs/run-001")) return json({ run_id: "run-001", status: "waiting" });
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
    if (pathname.endsWith("/v1/human-gates/gate-001")) return json({ gate_id: "gate-001", status: "pending" });
    if (pathname.includes("/v1/human-gates/gate-001/decision")) return json({ run_id: "run-001", status: "succeeded" });
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
  await expect(page.getByRole("heading", { name: "你想先做哪一类 AI 应用？" })).toBeVisible();
  await expect(page.getByText("基于企业知识回答", { exact: true })).toBeVisible();
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

test("effective configuration is read-only and explains field sources", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixtureApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "配置", exact: true }).click();
  await expect(page.getByRole("heading", { name: "当前生效配置" })).toBeVisible();
  await expect(page.getByText("gaia.yaml", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".config-form input:not([readonly])")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /保存|校验|激活|创建/ })).toHaveCount(0);
  await page.getByRole("tab", { name: "模型与流程" }).click();
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
  await page.getByRole("heading", { name: "按 Run ID 查询" }).locator("..").getByRole("button", { name: "查询" }).click();
  await page.getByRole("tab", { name: "事件链" }).click();
  await expect(page.getByText("run.created")).toBeVisible();
  await page.getByRole("tab", { name: "模型调用" }).click();
  await expect(page.getByRole("heading", { name: "模型调用" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "deterministic-mock" })).toBeVisible();
  await page.getByRole("tab", { name: "安全决策" }).click();
  await expect(page.getByRole("heading", { name: "安全决策" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "模型输入" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "已阻断" })).toBeVisible();
  await expect(page.getByText("PII_REDACTED", { exact: true })).toBeVisible();
  await page.getByLabel("Gate ID").fill("gate-001");
  await page.getByRole("heading", { name: "按审批 ID 查询" }).locator("..").getByRole("button", { name: "查询" }).click();
  await expect(page.getByText("等待处理")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("console-mobile-operations.png"), fullPage: true });
  await page.getByRole("button", { name: "测试" }).click();
  await page.getByRole("button", { name: "运行测试" }).click();
  await expect(page.getByText("replay-001")).toBeVisible();
  await expect(page.getByText("100.0%")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("console-mobile.png"), fullPage: true });
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
