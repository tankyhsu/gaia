import {
  Activity,
  ArrowRight,
  BookOpen,
  Boxes,
  CheckCircle2,
  CircleDashed,
  CircleAlert,
  ClipboardList,
  ExternalLink,
  FileText,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Upload,
} from "lucide-react";
import { useEffect, useState } from "react";

import {
  actuator,
  applyProjectInit,
  completeProjectInit,
  decideGate,
  getEvents,
  getGuardrailDecisions,
  getGate,
  getModelInvocations,
  getRun,
  importPrompt,
  inspectProjectInit,
  inspectPrompt,
  inspectPromptWorkspace,
  publishPrompt,
  rollbackPrompt,
  runReplay,
  runtimeSummary,
} from "./api";
import { ConfigForm, StructuredView, displayValue } from "./StructuredView";
import type {
  GuardrailDecision,
  ProjectInitSnapshot,
  PromptArtifact,
  PromptRelease,
  PromptVersion,
  PromptWorkspaceStatus,
  PromptWorkspaceSnapshot,
  RuntimeSummary,
  RunGuardrailObservability,
  RunModelObservability,
} from "./types";

type State = Record<string, unknown>;

interface ConfigSnapshot {
  config: State;
  origins: State;
  configHash: string;
}

const navigation = [
  ["overview", "概览", Activity],
  ["components", "组件", Boxes],
  ["runs", "运行", ShieldCheck],
  ["config", "配置", SlidersHorizontal],
  ["prompts", "Prompt", FileText],
  ["tests", "测试", ClipboardList],
] as const;

const QUICKSTART_DISMISSED_KEY = "gaia.dev-console.quickstart.dismissed";
const DEVELOPER_DOCS_URL =
  import.meta.env.VITE_GAIA_DOCS_URL ||
  `${location.protocol}//${location.hostname}:4175/`;

const pageAliases: Record<string, string> = {
  workbench: "overview",
  onboarding: "quickstart",
  verification: "overview",
  assembly: "components",
  capabilities: "components",
  governance: "runs",
  quality: "tests",
  actuator: "overview",
};

function initialPage() {
  const requested = location.hash.slice(1);
  if (requested) return pageAliases[requested] ?? requested;
  return localStorage.getItem(QUICKSTART_DISMISSED_KEY) === "true"
    ? "overview"
    : "quickstart";
}

function message(error: unknown) {
  return error instanceof Error ? error.message : "请求失败";
}

function items(value: unknown): State[] {
  return Array.isArray(value)
    ? value.filter(
        (entry): entry is State => Boolean(entry && typeof entry === "object"),
      )
    : [];
}

export function Console() {
  const [page, setPage] = useState(initialPage);
  const [info, setInfo] = useState<State | null>(null);
  const [health, setHealth] = useState<State | null>(null);
  const [components, setComponents] = useState<State[]>([]);
  const [configSnapshot, setConfigSnapshot] =
    useState<ConfigSnapshot | null>(null);
  const [runtime, setRuntime] = useState<RuntimeSummary | null>(null);
  const [error, setError] = useState("");

  async function refreshRuntime() {
    setRuntime(await runtimeSummary());
  }

  async function refreshCore() {
    const [nextInfo, nextHealth, nextComponents, nextConfig, nextRuntime] =
      await Promise.all([
        actuator<State>("info"),
        actuator<State>("health"),
        actuator<unknown>("components"),
        actuator<State>("config"),
        runtimeSummary(),
      ]);
    setInfo(nextInfo);
    setHealth(nextHealth);
    setComponents(items(nextComponents));
    setConfigSnapshot({
      config: record(nextConfig.config),
      origins: record(nextConfig.origins),
      configHash: String(nextConfig.config_hash ?? "-"),
    });
    setRuntime(nextRuntime);
  }

  useEffect(() => {
    refreshCore().catch((cause) => setError(message(cause)));
  }, []);

  async function refreshAll() {
    setError("");
    try {
      await refreshCore();
    } catch (cause) {
      setError(message(cause));
    }
  }

  function go(next: string) {
    if (page === "quickstart" && next !== "quickstart") {
      localStorage.setItem(QUICKSTART_DISMISSED_KEY, "true");
    }
    setPage(next);
    location.hash = next;
  }

  function finishQuickStart() {
    localStorage.setItem(QUICKSTART_DISMISSED_KEY, "true");
    go("overview");
  }

  if (error) {
    return (
      <main className="console-error">
        <h1>控制面不可用</h1>
        <p>{error}</p>
      </main>
    );
  }
  if (!info || !health || !runtime || !configSnapshot) {
    return <main className="console-loading">正在加载应用状态...</main>;
  }

  return (
    <div className="console-shell">
      <aside className="console-sidebar">
        <div className="console-brand">
          <Boxes size={19} />
          <div className="console-brand-copy">
            <strong>Gaia</strong>
            <small>Dev Console</small>
          </div>
        </div>
        {navigation.map(([id, label, Icon]) => (
          <button
            key={id}
            className={page === id ? "selected" : ""}
            onClick={() => go(id)}
          >
            <Icon size={16} />
            {label}
          </button>
          ))}
        <div className="sidebar-guide">
          <button
            className={page === "quickstart" ? "selected" : ""}
            onClick={() => go("quickstart")}
          >
            <BookOpen size={16} />
            快速开始
          </button>
          <a href={DEVELOPER_DOCS_URL} target="_blank" rel="noreferrer">
            <ExternalLink size={16} />
            Gaia 文档
          </a>
        </div>
      </aside>
      <section className="console-main">
        <header className="console-top">
          <div>
            <strong>{String(info.application_name ?? "Gaia Application")}</strong>
            <span>{String(info.application_version ?? "")}</span>
          </div>
          <div>
            <span className="dev-badge">开发工具</span>
            <span className="profile">{String(info.profile ?? "default")}</span>
            <span className="health">
              <CheckCircle2 size={14} /> {String(info.state ?? "UP")}
            </span>
          </div>
        </header>
        <ConsolePage
          page={page}
          info={info}
          health={health}
          components={components}
          configSnapshot={configSnapshot}
          runtime={runtime}
          refreshRuntime={refreshRuntime}
          refreshAll={refreshAll}
          finishQuickStart={finishQuickStart}
        />
      </section>
    </div>
  );
}

interface ConsolePageProps {
  page: string;
  info: State;
  health: State;
  components: State[];
  configSnapshot: ConfigSnapshot;
  runtime: RuntimeSummary;
  refreshRuntime: () => Promise<void>;
  refreshAll: () => Promise<void>;
  finishQuickStart: () => void;
}

function ConsolePage({
  page,
  info,
  health,
  components,
  configSnapshot,
  runtime,
  refreshRuntime,
  refreshAll,
  finishQuickStart,
}: ConsolePageProps) {
  if (page === "quickstart") {
    return <QuickStartConsole finish={finishQuickStart} />;
  }
  if (page === "components") {
    return (
      <section className="console-page">
        <PageHeading title="组件" refresh={refreshAll} />
        <ComponentCenter
          config={configSnapshot.config}
          components={components}
          health={health}
        />
      </section>
    );
  }
  if (page === "config") {
    return (
      <ConfigurationConsole
        snapshot={configSnapshot}
        info={info}
        refresh={refreshAll}
      />
    );
  }
  if (page === "runs") {
    return <RunConsole summary={runtime} refreshSummary={refreshRuntime} />;
  }
  if (page === "prompts") {
    return (
      <PromptWorkspace
        config={record(configSnapshot.config.prompt)}
        devtoolsEnabled={info.devtools_enabled === true}
      />
    );
  }
  if (page === "tests") {
    return <ReplayConsole />;
  }
  return (
    <OverviewConsole
      info={info}
      health={health}
      config={configSnapshot.config}
      components={components}
      runtime={runtime}
      refresh={refreshAll}
    />
  );
}

type PromptTab = "versions" | "releases" | "import";

const initialPromptArtifact = JSON.stringify(
  {
    prompt_id: "summary",
    version: "1.0.0",
    input_schema: {
      type: "object",
      properties: { text: { type: "string" } },
      required: ["text"],
    },
    messages: [
      { role: "system", content: "Produce a concise, factual summary." },
      { role: "user", content: "{text}" },
    ],
    model_requirements: {},
    metadata: { owner: "application" },
  },
  null,
  2,
);

function PromptWorkspace({
  config,
  devtoolsEnabled,
}: {
  config: State;
  devtoolsEnabled: boolean;
}) {
  const configuredProvider = promptProvider(config.provider);
  const [workspaceStatus, setWorkspaceStatus] =
    useState<PromptWorkspaceStatus | null>(null);
  const [statusError, setStatusError] = useState("");
  const [promptId, setPromptId] = useState("summary");
  const [tab, setTab] = useState<PromptTab>("versions");
  const [snapshot, setSnapshot] = useState<PromptWorkspaceSnapshot | null>(null);
  const [selected, setSelected] = useState<PromptVersion | null>(null);
  const [environment, setEnvironment] =
    useState<PromptRelease["environment"]>("sandbox");
  const [artifactText, setArtifactText] = useState(initialPromptArtifact);
  const [busy, setBusy] = useState(false);
  const [workspaceError, setWorkspaceError] = useState("");

  useEffect(() => {
    if (!devtoolsEnabled) {
      setWorkspaceStatus(null);
      return;
    }
    inspectPromptWorkspace()
      .then((status) => {
        setWorkspaceStatus(status);
        setStatusError("");
      })
      .catch((cause) => {
        setWorkspaceStatus(null);
        setStatusError(message(cause));
      });
  }, [devtoolsEnabled]);

  async function load(id = promptId) {
    setBusy(true);
    setWorkspaceError("");
    try {
      const next = await inspectPrompt(id);
      setSnapshot(next);
      setSelected(next.versions[0] ?? null);
    } catch (cause) {
      setSnapshot(null);
      setSelected(null);
      setWorkspaceError(message(cause));
    } finally {
      setBusy(false);
    }
  }

  async function importArtifact() {
    setBusy(true);
    setWorkspaceError("");
    try {
      const parsed = JSON.parse(artifactText) as PromptArtifact;
      await importPrompt(parsed);
      setPromptId(parsed.prompt_id);
      setTab("versions");
      await load(parsed.prompt_id);
    } catch (cause) {
      setWorkspaceError(message(cause));
    } finally {
      setBusy(false);
    }
  }

  async function moveRelease(rollback: boolean) {
    if (!selected) return;
    setBusy(true);
    setWorkspaceError("");
    try {
      if (rollback) {
        await rollbackPrompt(
          selected.artifact.prompt_id,
          selected.artifact.version,
          environment,
        );
      } else {
        await publishPrompt(
          selected.artifact.prompt_id,
          selected.artifact.version,
          environment,
        );
      }
      await load(selected.artifact.prompt_id);
      setTab("releases");
    } catch (cause) {
      setWorkspaceError(message(cause));
    } finally {
      setBusy(false);
    }
  }

  const provider = workspaceStatus?.provider ?? configuredProvider;
  if (provider === "disabled") {
    return <PromptProviderSelection />;
  }
  if (!devtoolsEnabled) {
    return (
      <PromptWorkspaceUnavailable
        provider={provider}
        root={String(config.root ?? "prompts")}
      />
    );
  }
  if (statusError) {
    return (
      <PromptWorkspaceError
        provider={provider}
        detail={statusError}
      />
    );
  }
  if (workspaceStatus === null) {
    return <main className="console-loading">正在读取 Prompt 工作区...</main>;
  }
  if (workspaceStatus.provider === "file") {
    return <FilePromptWorkspace value={workspaceStatus} />;
  }

  const currentRelease = snapshot?.releases.find(
    (release) => release.environment === environment,
  );
  const canPublish = selected?.status === "validating";
  const canRollback =
    selected?.status === "published" &&
    currentRelease !== undefined &&
    currentRelease.version !== selected.artifact.version;

  return (
    <section className="console-page">
      <div className="page-title">
        <h1>Prompt Registry</h1>
        <div className="prompt-search">
          <input
            aria-label="Prompt ID"
            value={promptId}
            onChange={(event) => setPromptId(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void load();
            }}
          />
          <button
            className="primary-button"
            onClick={() => void load()}
            disabled={busy || !promptId}
          >
            <Search size={15} />
            查询
          </button>
        </div>
      </div>
      <div className="summary-grid prompt-summary">
        <Metric label="Provider" value="PostgreSQL Registry" />
        <Metric label="访问模式" value="版本管理" />
        <Metric
          label="当前 Prompt"
          value={snapshot?.prompt_id ?? "尚未查询"}
        />
        <Metric
          label="环境指针"
          value={String(snapshot?.releases.length ?? 0)}
        />
      </div>
      <div className="workspace-tabs" role="tablist" aria-label="Prompt 视图">
        {(
          [
            ["versions", "版本"],
            ["releases", "环境指针"],
            ["import", "导入 Draft"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? "selected" : ""}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>
      {workspaceError ? (
        <div className="inline-error">{workspaceError}</div>
      ) : null}
      {tab === "versions" ? (
        <PromptVersions
          versions={snapshot?.versions ?? []}
          selected={selected}
          onSelect={setSelected}
        />
      ) : null}
      {tab === "releases" ? (
        <PromptReleases releases={snapshot?.releases ?? []} />
      ) : null}
      {tab === "import" ? (
        <div className="prompt-import">
          <textarea
            aria-label="Prompt Artifact JSON"
            value={artifactText}
            onChange={(event) => setArtifactText(event.target.value)}
            spellCheck={false}
          />
          <button
            className="primary-button"
            onClick={() => void importArtifact()}
            disabled={busy}
          >
            <Upload size={15} />
            导入 Draft
          </button>
        </div>
      ) : null}
      {tab === "versions" && selected ? (
        <div className="prompt-actionbar">
          <div>
            <strong>{selected.artifact.version}</strong>
            <code>{selected.artifact.content_hash.slice(0, 12)}</code>
          </div>
          <select
            aria-label="发布环境"
            value={environment}
            onChange={(event) =>
              setEnvironment(event.target.value as PromptRelease["environment"])
            }
          >
            <option value="mock">mock</option>
            <option value="sandbox">sandbox</option>
            <option value="customer">customer</option>
          </select>
          <button
            className="primary-button"
            disabled={busy || (!canPublish && !canRollback)}
            onClick={() => void moveRelease(canRollback)}
          >
            {canRollback ? "回滚到此版本" : "发布此版本"}
          </button>
        </div>
      ) : null}
    </section>
  );
}

function PromptProviderSelection() {
  return (
    <section className="console-page">
      <div className="page-title">
        <h1>Prompt</h1>
      </div>
      <div className="summary-grid">
        <Metric label="当前状态" value="未启用" />
        <Metric label="Provider" value="disabled" />
        <Metric label="已发现版本" value="0" />
        <Metric label="访问模式" value="不可用" />
      </div>
      <div className="prompt-provider-state">
        <div className="section-heading">
          <div>
            <h2>选择适合应用的 Prompt 管理方式</h2>
            <p>当前应用没有装配 Prompt Provider。</p>
          </div>
        </div>
        <table>
          <thead>
            <tr>
              <th>方式</th>
              <th>适合场景</th>
              <th>版本管理</th>
              <th>Console 能力</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>文件 Prompt</strong></td>
              <td>简单应用、Git 协作</td>
              <td>版本化 YAML</td>
              <td>只读清单</td>
            </tr>
            <tr>
              <td><strong>Prompt Registry</strong></td>
              <td>频繁调整、多人协作</td>
              <td>Draft、验证、发布与回滚</td>
              <td>版本工作区</td>
            </tr>
          </tbody>
        </table>
        <a
          className="secondary-button prompt-doc-link"
          href={`${DEVELOPER_DOCS_URL}mechanisms/`}
          target="_blank"
          rel="noreferrer"
        >
          查看开发者文档
          <ExternalLink size={15} />
        </a>
      </div>
    </section>
  );
}

function PromptWorkspaceUnavailable({
  provider,
  root,
}: {
  provider: "file" | "postgres";
  root: string;
}) {
  return (
    <section className="console-page">
      <div className="page-title">
        <h1>Prompt</h1>
      </div>
      <div className="summary-grid">
        <Metric label="Provider" value={promptProviderLabel(provider)} />
        <Metric label="组件状态" value="已配置" />
        <Metric label="工作区" value="未开启" />
        <Metric label="访问模式" value="只读说明" />
      </div>
      <div className="prompt-provider-state">
        <h2>Prompt Provider 已配置</h2>
        <p>
          当前进程没有开启开发工作区。应用运行不受影响，Console 不会尝试调用未注册的写接口。
        </p>
        {provider === "file" ? (
          <dl className="prompt-state-details">
            <dt>文件目录</dt>
            <dd>{root}</dd>
          </dl>
        ) : null}
      </div>
    </section>
  );
}

function PromptWorkspaceError({
  provider,
  detail,
}: {
  provider: "file" | "postgres";
  detail: string;
}) {
  return (
    <section className="console-page">
      <div className="page-title">
        <h1>Prompt</h1>
      </div>
      <div className="prompt-provider-state">
        <h2>{promptProviderLabel(provider)} 工作区不可用</h2>
        <p>{detail}</p>
      </div>
    </section>
  );
}

function FilePromptWorkspace({ value }: { value: PromptWorkspaceStatus }) {
  return (
    <section className="console-page">
      <div className="page-title">
        <h1>文件 Prompt</h1>
      </div>
      <div className="summary-grid prompt-summary">
        <Metric label="Provider" value="文件" />
        <Metric label="访问模式" value="只读" />
        <Metric label="Artifact" value={String(value.artifacts.length)} />
        <Metric label="组件" value={value.component_id ?? "-"} />
      </div>
      <dl className="prompt-state-details">
        <dt>根目录</dt>
        <dd>{value.root ?? "-"}</dd>
      </dl>
      <table className="prompt-table file-prompt-table">
        <thead>
          <tr>
            <th>Prompt</th>
            <th>版本</th>
            <th>文件</th>
            <th>内容哈希</th>
          </tr>
        </thead>
        <tbody>
          {value.artifacts.length ? (
            value.artifacts.map((artifact) => (
              <tr key={`${artifact.prompt_id}:${artifact.version}`}>
                <td><strong>{artifact.prompt_id}</strong></td>
                <td>{artifact.version}</td>
                <td>{artifact.relative_path}</td>
                <td><code>{artifact.content_hash.slice(0, 12)}</code></td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={4}>当前目录中没有版本化 Prompt Artifact</td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}

function promptProvider(value: unknown): "disabled" | "file" | "postgres" {
  return value === "file" || value === "postgres" ? value : "disabled";
}

function promptProviderLabel(provider: "file" | "postgres"): string {
  return provider === "file" ? "文件 Prompt" : "PostgreSQL Registry";
}

function PromptVersions({
  versions,
  selected,
  onSelect,
}: {
  versions: PromptVersion[];
  selected: PromptVersion | null;
  onSelect: (value: PromptVersion) => void;
}) {
  return (
    <table className="prompt-table">
      <thead>
        <tr>
          <th>版本</th>
          <th>状态</th>
          <th>内容哈希</th>
          <th>质量证据</th>
          <th>更新时间</th>
        </tr>
      </thead>
      <tbody>
        {versions.length ? (
          versions.map((version) => (
            <tr
              key={version.artifact.version}
              className={
                selected?.artifact.version === version.artifact.version
                  ? "selected"
                  : ""
              }
              onClick={() => onSelect(version)}
            >
              <td>
                <strong>{version.artifact.version}</strong>
              </td>
              <td>{promptStatus(version.status)}</td>
              <td>
                <code>{version.artifact.content_hash.slice(0, 12)}</code>
              </td>
              <td>
                {version.validation
                  ? `${version.validation.dataset_id} · ${version.validation.dataset_version}`
                  : "待验证"}
              </td>
              <td>{new Date(version.updated_at).toLocaleString()}</td>
            </tr>
          ))
        ) : (
          <tr>
            <td colSpan={5}>暂无版本</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

function PromptReleases({ releases }: { releases: PromptRelease[] }) {
  return (
    <table className="prompt-table">
      <thead>
        <tr>
          <th>环境</th>
          <th>版本</th>
          <th>内容哈希</th>
          <th>发布人</th>
          <th>更新时间</th>
        </tr>
      </thead>
      <tbody>
        {releases.length ? (
          releases.map((release) => (
            <tr key={release.environment}>
              <td>
                <strong>{release.environment}</strong>
              </td>
              <td>{release.version}</td>
              <td>
                <code>{release.content_hash.slice(0, 12)}</code>
              </td>
              <td>{release.updated_by}</td>
              <td>{new Date(release.updated_at).toLocaleString()}</td>
            </tr>
          ))
        ) : (
          <tr>
            <td colSpan={5}>暂无环境指针</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

function promptStatus(status: PromptVersion["status"]) {
  return {
    draft: "Draft",
    validating: "已验证",
    published: "已发布",
    retired: "已退役",
  }[status];
}

type CheckState = "passed" | "attention" | "pending";

interface IntegrationCheck {
  label: string;
  value: string;
  detail: string;
  state: CheckState;
}

interface ComponentView {
  key: string;
  kind: string;
  label: string;
  selection: string;
  componentId: string;
  implementation: string;
  source: string;
  assemblyLabel: string;
  assemblyState: CheckState;
  healthLabel: string;
  healthState: CheckState;
  required: string;
  errorCode: string;
}

function QuickStartConsole({ finish }: { finish: () => void }) {
  const [projectInit, setProjectInit] = useState<ProjectInitSnapshot | null>(null);
  const [templateId, setTemplateId] = useState("basic");
  const [selectedComponents, setSelectedComponents] = useState<string[]>([]);
  const [initError, setInitError] = useState("");
  const [initBusy, setInitBusy] = useState(false);

  useEffect(() => {
    inspectProjectInit()
      .then((snapshot) => {
        setProjectInit(snapshot);
        setTemplateId(snapshot.template_id);
        setSelectedComponents(
          snapshot.components
            .filter((component) => snapshot.starters.includes(component.starter))
            .map((component) => component.id),
        );
      })
      .catch(() => setProjectInit(null));
  }, []);

  function chooseTemplate(next: string) {
    setTemplateId(next);
    const recommended =
      projectInit?.templates.find((item) => item.id === next)
        ?.recommended_components ?? [];
    setSelectedComponents((current) => [
      ...new Set([...current, ...recommended]),
    ]);
  }

  function toggleComponent(componentId: string) {
    setSelectedComponents((current) =>
      current.includes(componentId)
        ? current.filter((item) => item !== componentId)
        : [...current, componentId],
    );
  }

  async function applySelection() {
    setInitBusy(true);
    setInitError("");
    try {
      await applyProjectInit(templateId, selectedComponents);
      setProjectInit((current) =>
        current
          ? { ...current, applied: true, template_id: templateId }
          : current,
      );
    } catch (cause) {
      setInitError(message(cause));
    } finally {
      setInitBusy(false);
    }
  }

  async function completeSelection() {
    setInitBusy(true);
    setInitError("");
    try {
      await completeProjectInit();
      finish();
    } catch (cause) {
      setInitError(message(cause));
      setInitBusy(false);
    }
  }

  return (
    <section className="console-page">
      <div className="quickstart-heading">
        <div>
          <span>首次启动引导</span>
          <h1>Gaia</h1>
          <p>
            从一个接近你业务想法的场景开始，Gaia 会生成项目起点并推荐所需能力。你可以先用
            示例模型和数据验证流程，再逐步接入企业知识与业务系统。
          </p>
        </div>
        <div className="quickstart-heading-actions">
          <a
            className="secondary-button"
            href={DEVELOPER_DOCS_URL}
            target="_blank"
            rel="noreferrer"
          >
            Gaia 文档
            <ExternalLink size={15} />
          </a>
          <button className="secondary-button" onClick={finish}>
            跳过引导
            <ArrowRight size={15} />
          </button>
        </div>
      </div>
      {projectInit && (
        <section className="project-init">
          <div className="section-heading">
            <div>
              <h2>你想先做哪一类 AI 应用？</h2>
              <p>选择最接近的目标，Gaia 会生成对应代码并推荐所需组件。</p>
            </div>
          </div>
          <div className="template-options">
            {projectInit.templates.map((template) => (
              <label
                className={templateId === template.id ? "selected" : ""}
                key={template.id}
              >
                <input
                  type="radio"
                  name="scenario-template"
                  value={template.id}
                  checked={templateId === template.id}
                  disabled={!projectInit.available}
                  onChange={() => chooseTemplate(template.id)}
                />
                <span>
                  <strong>{template.name}</strong>
                  <small>{template.description}</small>
                </span>
              </label>
            ))}
          </div>
          <div className="quickstart-safety">
            <div className="section-heading">
              <div>
                <h2>从 Demo 开始，也保留安全边界</h2>
                <p>
                  Gaia 可以在内容进入模型、引用企业知识和执行系统操作时检查风险。
                </p>
              </div>
            </div>
            <div className="safety-steps">
              <div>
                <strong>处理内容</strong>
                <span>发送给模型前识别风险，必要时脱敏或停止处理。</span>
              </div>
              <div>
                <strong>引用知识</strong>
                <span>企业资料进入回答前检查权限和上下文污染。</span>
              </div>
              <div>
                <strong>执行操作</strong>
                <span>调用业务系统前后检查参数、结果和操作范围。</span>
              </div>
            </div>
            <p className="quickstart-safety-note">
              运行后，可在“运行 → 安全决策”查看放行、改写和阻断原因。
            </p>
          </div>
          <details className="component-adjustments">
            <summary>
              <strong>调整组件</strong>
              <span>Gaia 已按场景推荐，熟悉后可按需修改</span>
            </summary>
            <div className="component-options">
              {projectInit.components.map((component) => (
                <label key={component.id}>
                  <input
                    type="checkbox"
                    checked={selectedComponents.includes(component.id)}
                    disabled={!projectInit.available}
                    onChange={() => toggleComponent(component.id)}
                  />
                  <span>
                    <strong>{component.name}</strong>
                    <small>{component.starter}</small>
                  </span>
                </label>
              ))}
            </div>
          </details>
          {initError && (
            <p className="console-notice" role="alert">
              {initError}
            </p>
          )}
          <div className="quickstart-actions">
            {!projectInit.available ? (
              <p>当前项目已经完成初始化；这里保留场景说明供开发时查阅。</p>
            ) : projectInit.applied ? (
              <>
                <p>场景和组件已经写入项目，开发服务重载后即可完成初始化。</p>
                <button
                  className="primary-button"
                  disabled={initBusy}
                  onClick={completeSelection}
                >
                  <CheckCircle2 size={15} />
                  完成并进入概览
                </button>
              </>
            ) : (
              <button
                className="primary-button"
                disabled={initBusy}
                onClick={applySelection}
              >
                <Play size={15} />
                {initBusy ? "正在生成..." : "生成场景并应用组件"}
              </button>
            )}
          </div>
        </section>
      )}
    </section>
  );
}

function OverviewConsole({
  info,
  health,
  config,
  components,
  runtime,
  refresh,
}: {
  info: State;
  health: State;
  config: State | null;
  components: State[];
  runtime: RuntimeSummary;
  refresh: () => Promise<void>;
}) {
  const checks = integrationChecks(info, health, components, runtime);
  const passed = checks.filter((item) => item.state === "passed").length;
  return (
    <section className="console-page">
      <PageHeading title="概览" refresh={refresh} />
      <h2>当前应用</h2>
      <div className="summary-grid overview-summary">
        <Metric
          label="接入状态"
          value={passed === checks.length ? "已验证" : `${passed} / ${checks.length}`}
        />
        <Metric label="配置方案" value={String(info.profile ?? "-")} />
        <Metric
          label="运行环境"
          value={configValue(config, "runtime", "environment")}
        />
        <Metric
          label="框架版本"
          value={String(info.framework_version ?? "-")}
        />
      </div>
      <div className="integration-steps">
        {checks.map((check, index) => (
          <div className="integration-step" key={check.label}>
            <span className="step-index">{index + 1}</span>
            <div>
              <strong>{check.label}</strong>
              <span>{check.detail}</span>
            </div>
            <span className="step-value">{check.value}</span>
            <StatusMark state={check.state} />
          </div>
        ))}
      </div>
    </section>
  );
}

function PageHeading({
  title,
  refresh,
}: {
  title: string;
  refresh: () => Promise<void>;
}) {
  return (
    <div className="page-title">
      <h1>{title}</h1>
      <button className="primary-button" onClick={refresh}>
        <RefreshCw size={15} />
        刷新状态
      </button>
    </div>
  );
}

function ComponentCenter({
  config,
  components,
  health,
}: {
  config: State | null;
  components: State[];
  health: State;
}) {
  const rows = componentViews(config, components, health);
  const healthy = rows.filter((row) => row.healthState === "passed").length;
  const attention = rows.filter(
    (row) =>
      row.assemblyState === "attention" || row.healthState === "attention",
  ).length;
  return (
    <>
      <div className="summary-grid">
        <Metric label="已注册组件" value={String(components.length)} />
        <Metric
          label="能力类型"
          value={String(new Set(components.map((item) => item.kind)).size)}
        />
        <Metric label="健康组件" value={String(healthy)} />
        <Metric label="需要处理" value={String(attention)} />
      </div>
      <h2>组件清单</h2>
      <table className="component-table">
        <thead>
          <tr>
            <th>能力与组件</th>
            <th>当前选择</th>
            <th>实现与来源</th>
            <th>装配</th>
            <th>健康</th>
            <th>必需</th>
            <th>错误码</th>
          </tr>
        </thead>
        <tbody>
          {rows.length ? (
            rows.map((row) => (
              <tr key={row.key}>
                <td>
                  <div className="component-identity">
                    <strong>{row.label}</strong>
                    <span>{row.componentId}</span>
                  </div>
                </td>
                <td>{row.selection}</td>
                <td>
                  <div className="component-identity">
                    <strong>{row.implementation}</strong>
                    <span>{row.source}</span>
                  </div>
                </td>
                <td>
                  <StatusMark
                    state={row.assemblyState}
                    label={row.assemblyLabel}
                  />
                </td>
                <td>
                  <StatusMark
                    state={row.healthState}
                    label={row.healthLabel}
                  />
                </td>
                <td>{row.required}</td>
                <td>{row.errorCode}</td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={7}>暂无组件信息</td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}

function StatusMark({
  state,
  label,
}: {
  state: CheckState;
  label?: string;
}) {
  const Icon =
    state === "passed"
      ? CheckCircle2
      : state === "attention"
        ? CircleAlert
        : CircleDashed;
  const text =
    label ??
    {
      passed: "已通过",
      attention: "需处理",
      pending: "未启用",
    }[state];
  return (
    <span className={`status-mark ${state}`}>
      <Icon size={14} />
      {text}
    </span>
  );
}

function integrationChecks(
  info: State,
  health: State,
  components: State[],
  runtime: RuntimeSummary,
): IntegrationCheck[] {
  const kinds = new Set(components.map((item) => String(item.kind)));
  const requiredKinds = ["model", "workflow", "context", "persistence", "policy"];
  const graphReady = requiredKinds.every((kind) => kinds.has(kind));
  const successfulRuns = runtime.status_counts.succeeded ?? 0;
  return [
    {
      label: "应用配置",
      value: String(info.profile ?? "-"),
      detail: String(info.application_name ?? "Gaia Application"),
      state: info.state === "started" || info.state === "UP" ? "passed" : "attention",
    },
    {
      label: "核心能力",
      value: `${components.length} 个组件`,
      detail: graphReady
        ? "模型、流程、上下文、持久化和安全策略已装配"
        : "核心组件尚未完整装配",
      state: graphReady ? "passed" : "attention",
    },
    {
      label: "运行时健康",
      value: String(health.status ?? "-"),
      detail: `${runtime.database.backend} · 等待 ${runtime.database.waiting_connections ?? 0}`,
      state: health.status === "UP" ? "passed" : "attention",
    },
    {
      label: "应用流程",
      value: kinds.has("workflow") ? "已注册" : "未注册",
      detail: kinds.has("workflow")
        ? "应用 Runner 已进入组件图"
        : "尚未发现应用流程组件",
      state: kinds.has("workflow") ? "passed" : "attention",
    },
    {
      label: "最小运行验证",
      value: successfulRuns ? `${successfulRuns} 次成功` : "尚未运行",
      detail: successfulRuns ? "最近 24 小时已有成功 Run" : "当前窗口内没有成功 Run",
      state: successfulRuns ? "passed" : "pending",
    },
  ];
}

function componentViews(
  config: State | null,
  components: State[],
  health: State,
): ComponentView[] {
  const selections = new Map<string, string>();
  for (const [key, value] of Object.entries(record(config))) {
    const provider = record(value).provider;
    if (typeof provider === "string") {
      selections.set(key, provider);
    }
  }
  for (const [key, value] of Object.entries(record(record(config).stores))) {
    const provider = record(value).provider;
    if (typeof provider === "string") {
      selections.set(key === "operational" ? "persistence" : key, provider);
    }
  }
  for (const component of components) {
    const kind = String(component.kind ?? "custom");
    if (!selections.has(kind)) {
      selections.set(kind, "应用提供");
    }
  }
  const healthById = new Map(
    items(health.components).map((entry) => [
      String(entry.component_id ?? ""),
      entry,
    ]),
  );
  const rows: ComponentView[] = components.map((component, index) => {
    const kind = String(component.kind ?? "custom");
    const componentId = String(component.component_id ?? `${kind}-${index}`);
    const healthEntry = healthById.get(componentId);
    const componentHealth = record(healthEntry?.health);
    const healthStatus = String(componentHealth.status ?? "unknown").toLowerCase();
    const healthState: CheckState =
      healthStatus === "failed" || healthStatus === "down"
        ? "attention"
        : healthStatus === "unknown"
          ? "pending"
          : "passed";
    return {
      key: componentId,
      kind,
      label: capabilityLabel(kind),
      selection: selections.get(kind) ?? "应用提供",
      componentId,
      implementation: String(component.implementation ?? "-"),
      source: String(component.starter_id ?? "应用注册"),
      assemblyLabel: componentStatusLabel(component.status),
      assemblyState:
        String(component.status).toLowerCase() === "failed"
          ? "attention"
          : "passed",
      healthLabel:
        healthStatus === "unknown"
          ? "未检查"
          : componentHealthLabel(healthStatus),
      healthState,
      required:
        healthEntry === undefined
          ? "-"
          : healthEntry.required === false
            ? "否"
            : "是",
      errorCode: String(componentHealth.error_code ?? "-"),
    };
  });
  for (const [kind, selection] of selections) {
    if (components.some((component) => component.kind === kind)) continue;
    const disabled =
      selection === "disabled" || selection === "-" || selection === "未注册";
    rows.push({
      key: `missing-${kind}`,
      kind,
      label: capabilityLabel(kind),
      selection,
      componentId: "-",
      implementation: "-",
      source: "-",
      assemblyLabel: disabled ? "未启用" : "待装配",
      assemblyState: disabled ? "pending" : "attention",
      healthLabel: "-",
      healthState: "pending",
      required: "-",
      errorCode: "-",
    });
  }
  return rows.sort(
    (left, right) =>
      capabilityOrder(left.label) - capabilityOrder(right.label) ||
      left.label.localeCompare(right.label) ||
      left.componentId.localeCompare(right.componentId),
  );
}

function capabilityLabel(kind: string): string {
  return (
    {
      model: "模型",
      workflow: "流程引擎",
      context: "上下文",
      policy: "安全策略",
      tool: "工具调用",
      persistence: "运行持久化",
      checkpoint: "流程检查点",
      embedding: "向量模型",
      memory: "长期记忆",
      vector: "向量检索",
      rag: "知识检索",
      cache: "缓存",
      rate_limit: "限流",
      outbox: "可靠事件队列",
      event_publisher: "事件发布",
      evaluation: "测试评估",
      prompt: "Prompt",
    }[kind] ?? kind
  );
}

function capabilityOrder(label: string): number {
  const order = [
    "模型",
    "流程引擎",
    "上下文",
    "安全策略",
    "工具调用",
    "运行持久化",
    "流程检查点",
    "向量模型",
    "长期记忆",
    "向量检索",
    "知识检索",
    "缓存",
    "限流",
    "可靠事件队列",
    "事件发布",
    "测试评估",
    "Prompt",
  ];
  const index = order.indexOf(label);
  return index === -1 ? order.length : index;
}

function componentStatusLabel(value: unknown): string {
  return (
    {
      configured: "已装配",
      started: "已启动",
      up: "正常",
      healthy: "正常",
      failed: "失败",
      down: "不可用",
      unknown: "未检查",
    }[String(value).toLowerCase()] ?? String(value ?? "unknown")
  );
}

function componentHealthLabel(value: unknown): string {
  return (
    {
      configured: "正常",
      started: "正常",
      up: "正常",
      healthy: "正常",
      failed: "失败",
      down: "不可用",
    }[String(value).toLowerCase()] ?? String(value ?? "unknown")
  );
}

function configValue(config: State | null, ...path: string[]): string {
  let current: unknown = config;
  for (const key of path) {
    current = record(current)[key];
  }
  return current === null || current === undefined ? "-" : String(current);
}

function record(value: unknown): State {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as State)
    : {};
}

function OperationsOverview({ summary }: { summary: RuntimeSummary }) {
  return (
    <>
      <div className="summary-grid">
        <Metric label="成功率" value={formatRate(summary.success_rate)} />
        <Metric label="失败率" value={formatRate(summary.failure_rate)} />
        <Metric label="耗时 p95" value={formatDuration(summary.run_duration.p95_ms)} />
        <Metric label="待人工确认" value={String(summary.pending_human_gates)} />
      </div>
      <h2>等待与容量</h2>
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
        </tbody>
      </table>
    </>
  );
}

function IssueTable({ issues }: { issues: RuntimeSummary["issues"] }) {
  return (
    <>
      <h2>需要处理</h2>
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
          {issues.length ? (
            issues.map((issue) => (
              <tr key={issue.run_id}>
                <td>{issue.run_id}</td>
                <td>{issue.scenario_id}</td>
                <td>{issue.status}</td>
                <td>{bottleneckLabel(issue.bottleneck)}</td>
                <td>{formatAge(issue.age_seconds)}</td>
                <td>{issue.error_code ?? "-"}</td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={6}>当前窗口内没有待处理 Run</td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}

function ConfigurationConsole({
  snapshot,
  info,
  refresh,
}: {
  snapshot: ConfigSnapshot;
  info: State;
  refresh: () => Promise<void>;
}) {
  return (
    <section className="console-page">
      <PageHeading title="配置" refresh={refresh} />
      <div className="summary-grid">
        <Metric label="配置方案" value={String(info.profile ?? "-")} />
        <Metric label="配置指纹" value={shortHash(snapshot.configHash)} />
        <Metric
          label="字段来源"
          value={`${Object.keys(snapshot.origins).length} 项`}
        />
        <Metric label="运行配置" value="只读" />
      </div>
      <h2>当前生效配置</h2>
      <ConfigForm
        value={snapshot.config}
        origins={snapshot.origins}
      />
    </section>
  );
}

function RunConsole({
  summary,
  refreshSummary,
}: {
  summary: RuntimeSummary;
  refreshSummary: () => Promise<void>;
}) {
  const [runId, setRunId] = useState("");
  const [gateId, setGateId] = useState("");
  const [result, setResult] = useState<State | null>(null);
  const [events, setEvents] = useState<State[]>([]);
  const [gate, setGate] = useState<State | null>(null);
  const [modelObservability, setModelObservability] =
    useState<RunModelObservability | null>(null);
  const [guardrailObservability, setGuardrailObservability] =
    useState<RunGuardrailObservability | null>(null);
  const [detailTab, setDetailTab] = useState<RunDetailTab>("result");
  const [notice, setNotice] = useState("");

  async function inspect() {
    try {
      const [run, runEvents, observations, guardrails] = await Promise.all([
        getRun(runId),
        getEvents(runId),
        getModelInvocations(runId),
        getGuardrailDecisions(runId),
      ]);
      setResult(run as unknown as State);
      setEvents(runEvents as unknown as State[]);
      setModelObservability(observations);
      setGuardrailObservability(guardrails);
      setDetailTab("result");
      setNotice("");
    } catch (cause) {
      setNotice(message(cause));
    }
  }

  async function inspectGate() {
    try {
      setGate((await getGate(gateId)) as unknown as State);
      setNotice("");
    } catch (cause) {
      setNotice(message(cause));
    }
  }

  async function decide(decision: "approved" | "rejected") {
    try {
      setResult((await decideGate(gateId, decision)) as unknown as State);
      await Promise.all([inspectGate(), refreshSummary()]);
    } catch (cause) {
      setNotice(message(cause));
    }
  }

  return (
    <section className="console-page">
      <div className="page-title">
        <h1>运行</h1>
        <button className="primary-button" onClick={refreshSummary}>
          <RefreshCw size={15} />
          刷新
        </button>
      </div>
      <OperationsOverview summary={summary} />
      <IssueTable issues={summary.issues} />
      {notice && (
        <p className="console-notice" role="alert">
          {notice}
        </p>
      )}
      <div className="governance-grid governance-inspector">
        <section>
          <h2>按 Run ID 查询</h2>
          <div className="input-action">
            <input
              aria-label="Run ID"
              value={runId}
              onChange={(event) => setRunId(event.target.value)}
              placeholder="Run ID"
            />
            <button onClick={inspect} disabled={!runId}>
              查询
            </button>
          </div>
          {result && modelObservability && guardrailObservability ? (
            <RunDetail
              result={result}
              events={events}
              modelObservability={modelObservability}
              guardrailObservability={guardrailObservability}
              tab={detailTab}
              onTabChange={setDetailTab}
            />
          ) : null}
        </section>
        <section>
          <h2>按审批 ID 查询</h2>
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
          {gate && (
            <div className="inspection-result">
              <h3>审批详情</h3>
              <StructuredView value={gate} />
            </div>
          )}
          <div className="action-row">
            <button onClick={() => decide("approved")} disabled={!gateId}>
              批准
            </button>
            <button
              className="danger-button"
              onClick={() => decide("rejected")}
              disabled={!gateId}
            >
              拒绝
            </button>
          </div>
        </section>
      </div>
    </section>
  );
}

type RunDetailTab = "result" | "model" | "guardrails" | "events";

function RunDetail({
  result,
  events,
  modelObservability,
  guardrailObservability,
  tab,
  onTabChange,
}: {
  result: State;
  events: State[];
  modelObservability: RunModelObservability;
  guardrailObservability: RunGuardrailObservability;
  tab: RunDetailTab;
  onTabChange: (tab: RunDetailTab) => void;
}) {
  const tabs: Array<[RunDetailTab, string]> = [
    ["result", "运行结果"],
    ["model", "模型调用"],
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
      {tab === "result" ? (
        <div className="inspection-result">
          <StructuredView value={result} />
        </div>
      ) : null}
      {tab === "model" ? (
        <ModelObservationPanel value={modelObservability} />
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

function guardrailStageLabel(stage: GuardrailDecision["stage"]): string {
  return {
    input: "模型输入",
    retrieval: "知识检索",
    output: "模型输出",
    tool_input: "操作参数",
    tool_output: "操作结果",
  }[stage];
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

function ReplayConsole() {
  const [replay, setReplay] = useState<State | null>(null);
  const [notice, setNotice] = useState("");

  async function trigger() {
    try {
      setReplay((await runReplay()) as unknown as State);
    } catch (cause) {
      setNotice(message(cause));
    }
  }

  return (
    <section className="console-page">
      <div className="page-title">
        <h1>测试</h1>
        <button className="primary-button" onClick={trigger}>
          <Play size={15} />
          运行测试
        </button>
      </div>
      {notice && (
        <p className="console-notice" role="alert">
          {notice}
        </p>
      )}
      {replay ? (
        <ReplayResult value={replay} />
      ) : (
        <p className="empty-copy">尚未运行回归测试。</p>
      )}
    </section>
  );
}

function ReplayResult({ value }: { value: State }) {
  const results = items(value.results);
  const total = Number(value.total ?? results.length);
  const passed = Number(value.passed ?? 0);
  const failed = Number(value.failed ?? 0);
  return (
    <>
      <div className="summary-grid">
        <Metric label="测试状态" value={displayValue(value.status)} />
        <Metric label="通过率" value={total ? formatRate(passed / total) : "-"} />
        <Metric label="通过" value={String(passed)} />
        <Metric label="失败" value={String(failed)} />
      </div>
      <div className="run-metadata">
        <StructuredView
          value={{
            replay_id: value.replay_id,
            created_at: value.created_at,
            finished_at: value.finished_at,
          }}
        />
      </div>
      <h2>Case 结果</h2>
      <table>
        <thead>
          <tr>
            <th>Case ID</th>
            <th>结果</th>
            <th>预期状态</th>
            <th>实际状态</th>
          </tr>
        </thead>
        <tbody>
          {results.length ? (
            results.map((result, index) => (
              <tr key={String(result.case_id ?? index)}>
                <td>{String(result.case_id ?? "-")}</td>
                <td>
                  <StatusMark
                    state={result.passed === true ? "passed" : "attention"}
                    label={result.passed === true ? "通过" : "失败"}
                  />
                </td>
                <td>{displayValue(result.expected_status)}</td>
                <td>{displayValue(result.actual_status)}</td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={4}>接口未返回逐 Case 结果</td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <dl>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </dl>
  );
}

function formatRate(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function shortHash(value: string) {
  return value.length > 12 ? value.slice(0, 12) : value;
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
