import {
  Activity,
  Boxes,
  ExternalLink,
  Gauge,
  RefreshCw,
  Route,
  ScanSearch,
  ShieldCheck,
} from "lucide-react";

import type { RuntimeSummary } from "./types";

type State = Record<string, unknown>;

function record(value: unknown): State {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as State
    : {};
}

function text(value: unknown, fallback = "-"): string {
  return value === null || value === undefined || value === ""
    ? fallback
    : String(value);
}

function duration(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

function componentHealth(component: State): string {
  return text(record(component.health).status, text(component.status, "unknown"));
}

function healthLabel(status: string): string {
  return status === "configured" || status === "UP" ? "正常" : status;
}

export function ObservabilityView({
  runtime,
  observabilityConfig,
  components,
  health,
  refresh,
  onNavigate,
}: {
  runtime: RuntimeSummary;
  observabilityConfig: State;
  components: State[];
  health: State;
  refresh: () => Promise<void>;
  onNavigate: (page: string) => void;
}) {
  const provider = text(observabilityConfig.provider, "local");
  const externalEnabled = provider === "langfuse";
  const baseUrl = text(observabilityConfig.base_url, "");
  const healthyComponents = components.filter(
    (component) => componentHealth(component) === "configured",
  ).length;

  return (
    <section className="console-page observability-page">
      <div className="page-title observability-title">
        <div>
          <p className="page-eyebrow">运行与诊断</p>
          <h1>可观测</h1>
          <p className="page-description">
            从系统运行状态进入单次 Run 证据，并确认外部观测链路是否已配置。
          </p>
        </div>
        <button className="primary-button" onClick={refresh}>
          <RefreshCw size={15} />
          刷新
        </button>
      </div>

      <section className="observability-section" aria-labelledby="signals-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">系统现在怎样</p>
            <h2 id="signals-title">运行信号</h2>
          </div>
          <p>这些数据来自 Gaia Runtime，不依赖外部观测平台。</p>
        </div>
        <div className="signal-grid">
          <article className="signal-card signal-primary">
            <span>窗口内 Run</span>
            <strong>{runtime.total_runs}</strong>
            <small>{runtime.window_hours} 小时观测窗口</small>
          </article>
          <article className="signal-card signal-success">
            <span>已完成</span>
            <strong>{runtime.status_counts.succeeded ?? 0}</strong>
            <small>正常完成执行</small>
          </article>
          <article className="signal-card signal-controlled">
            <span>被控制拦下</span>
            <strong>{runtime.stopped_by_control}</strong>
            <small>策略或 Guardrail 正常生效</small>
          </article>
          <article className="signal-card signal-attention">
            <span>待人工确认</span>
            <strong>{runtime.pending_human_gates}</strong>
            <small>需要开发者或运营处理</small>
          </article>
          <article className="signal-card signal-danger">
            <span>失败 / 停滞</span>
            <strong>{runtime.status_counts.failed ?? 0} / {runtime.stale_runs}</strong>
            <small>优先进入 Run 页面定位</small>
          </article>
          <article className="signal-card">
            <span>Run 耗时 p95</span>
            <strong>{duration(runtime.run_duration.p95_ms)}</strong>
            <small>当前窗口执行耗时</small>
          </article>
        </div>
        <div className="observability-action-row">
          <button className="secondary-button" onClick={() => onNavigate("runs")}>
            <ScanSearch size={15} />
            查看 Run 与证据
          </button>
        </div>
      </section>

      <section className="observability-section" aria-labelledby="pipeline-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">数据流向哪里</p>
            <h2 id="pipeline-title">观测链路</h2>
          </div>
          <p>Gaia 保存执行事实；外部平台只接收安全的观测投影。</p>
        </div>
        <div className="telemetry-pipeline">
          <article className="telemetry-node active">
            <div className="telemetry-icon"><ShieldCheck size={20} /></div>
            <div>
              <span className="status-pill success">正在记录</span>
              <h3>Gaia 运行证据</h3>
              <p>Run、事件、模型调用、工具调用、Guardrail 和 Human Gate 是审计事实源。</p>
            </div>
          </article>
          <Route className="telemetry-arrow" size={24} aria-hidden="true" />
          <article className={`telemetry-node ${externalEnabled ? "active" : ""}`}>
            <div className="telemetry-icon"><Activity size={20} /></div>
            <div>
              <span className={`status-pill ${externalEnabled ? "success" : "muted"}`}>
                {externalEnabled ? "已启用" : "未启用"}
              </span>
              <h3>OpenTelemetry 导出</h3>
              <p>导出安全属性、模型 Token、耗时和成本指标，不传递请求与响应正文。</p>
            </div>
          </article>
          <Route className="telemetry-arrow" size={24} aria-hidden="true" />
          <article className={`telemetry-node ${externalEnabled ? "active" : ""}`}>
            <div className="telemetry-icon"><Gauge size={20} /></div>
            <div>
              <span className={`status-pill ${externalEnabled ? "success" : "muted"}`}>
                {externalEnabled ? "已配置" : "本地模式"}
              </span>
              <h3>Langfuse</h3>
              <p>
                {externalEnabled
                  ? "接收 Gaia 的 OTLP Trace 投影；连接状态仍需在目标平台确认。"
                  : "当前没有向 Langfuse 发送数据，Gaia 本地证据仍完整可查。"}
              </p>
              {externalEnabled && baseUrl ? (
                <a
                  href={
                    location.port === "4181"
                      ? `${location.protocol}//127.0.0.1:3000/`
                      : baseUrl
                  }
                  target="_blank"
                  rel="noreferrer"
                >
                  打开 Langfuse <ExternalLink size={13} />
                </a>
              ) : null}
            </div>
          </article>
        </div>
        <p className="telemetry-truth-note">
          当前 provider：<strong>{provider}</strong>
          {externalEnabled ? "。页面确认配置已装配，不把它误报成网络连通性检查。" : "。"}
        </p>
      </section>

      <section className="observability-section" aria-labelledby="coverage-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">能看到什么</p>
            <h2 id="coverage-title">观测覆盖</h2>
          </div>
          <p>先选问题类型，再进入对应 Console 能力。</p>
        </div>
        <div className="coverage-grid">
          <article>
            <Activity size={18} />
            <h3>Runtime 与容量</h3>
            <p>Run 状态、失败、控制拦截、人工等待、耗时、数据库连接和 Outbox。</p>
            <button onClick={() => onNavigate("runs")}>进入运行</button>
          </article>
          <article>
            <ScanSearch size={18} />
            <h3>单次执行</h3>
            <p>模型调用、Token、工具调用、策略决策、事件链和人工审批证据。</p>
            <button onClick={() => onNavigate("runs")}>选择 Run</button>
          </article>
          <article>
            <Boxes size={18} />
            <h3>组件健康</h3>
            <p>已装配组件、实现、依赖关系、配置来源和当前健康状态。</p>
            <button onClick={() => onNavigate("components")}>查看组件</button>
          </article>
        </div>
      </section>

      <section className="observability-section" aria-labelledby="components-health-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">当前装配</p>
            <h2 id="components-health-title">组件可见性</h2>
          </div>
          <p>
            {healthyComponents}/{components.length} 个注册组件处于 configured，
            控制面状态 {text(health.status)}。
          </p>
        </div>
        <div className="table-scroll">
          <table className="observable-components-table">
            <thead>
              <tr>
                <th>组件</th>
                <th>类别</th>
                <th>实现</th>
                <th>健康</th>
                <th>依赖</th>
              </tr>
            </thead>
            <tbody>
              {components.map((component) => (
                <tr key={text(component.component_id)}>
                  <td><strong>{text(component.component_id)}</strong></td>
                  <td>{text(component.kind)}</td>
                  <td className="implementation-cell" title={text(component.implementation)}>
                    {text(component.implementation)}
                  </td>
                  <td>
                    <span className="status-pill success">
                      {healthLabel(componentHealth(component))}
                    </span>
                  </td>
                  <td>{Array.isArray(component.depends_on) ? component.depends_on.length : 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="observability-action-row">
          <button className="secondary-button" onClick={() => onNavigate("components")}>
            <Boxes size={15} />
            管理组件装配
          </button>
          <button className="secondary-button" onClick={() => onNavigate("config")}>
            查看可观测配置
          </button>
        </div>
      </section>
    </section>
  );
}
