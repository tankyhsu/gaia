import { Fragment, useState } from "react";

export type DataRecord = Record<string, unknown>;

const labels: Record<string, string> = {
  application: "应用",
  name: "名称",
  version: "版本",
  profile: "运行配置",
  starters: "已启用 Starter",
  runtime: "运行时",
  environment: "运行环境",
  database_url: "数据库连接",
  max_steps: "最大步骤数",
  timeout_seconds: "超时时间（秒）",
  write_mode: "写入策略",
  stores: "数据存储",
  operational: "运行数据",
  checkpoint: "流程检查点",
  memory: "长期记忆",
  vector: "向量检索",
  provider: "实现方式",
  auto_create: "自动建表",
  auto_setup: "自动初始化",
  pool_size: "连接池大小",
  max_overflow: "最大额外连接",
  pool_timeout_seconds: "连接等待超时（秒）",
  pool_recycle_seconds: "连接回收时间（秒）",
  pool_min_size: "最小连接数",
  pool_max_size: "最大连接数",
  dimensions: "向量维度",
  distance_type: "距离算法",
  index_kind: "索引类型",
  vector_type: "向量类型",
  fields: "检索字段",
  redis: "Redis 连接",
  url: "连接地址",
  key_prefix: "Key 前缀",
  max_connections: "最大连接数",
  socket_timeout_seconds: "连接超时（秒）",
  health_check_interval_seconds: "健康检查间隔（秒）",
  cache: "缓存",
  default_ttl_seconds: "默认有效期（秒）",
  max_ttl_seconds: "最大有效期（秒）",
  rate_limit: "访问限流",
  outbox: "可靠事件",
  publisher: "发布方式",
  batch_size: "批量大小",
  lease_seconds: "任务租期（秒）",
  max_attempts: "最大重试次数",
  retry_delay_seconds: "重试间隔（秒）",
  model: "大模型",
  model_id: "模型名称",
  base_url: "服务地址",
  api_key: "API Key 来源",
  embedding: "Embedding",
  prompt: "Prompt",
  rag: "知识检索",
  root: "资源目录",
  namespace_prefix: "命名空间前缀",
  chunk_size: "分块长度",
  chunk_overlap: "分块重叠",
  candidate_multiplier: "候选放大倍数",
  workflow: "流程引擎",
  context: "上下文",
  policy: "安全策略",
  human_gate_ttl_seconds: "人工确认有效期（秒）",
  evaluation: "测试",
  cases: "测试集路径",
  env: "环境变量",
  file: "密钥文件",
  application_name: "应用名称",
  application_version: "应用版本",
  state: "运行状态",
  config_hash: "配置指纹",
  status: "状态",
  run_id: "Run ID",
  scenario_id: "场景",
  mode: "运行模式",
  pending_gate_id: "待处理审批",
  created_at: "创建时间",
  started_at: "开始时间",
  finished_at: "完成时间",
  updated_at: "更新时间",
  result: "执行结果",
  error: "错误",
  code: "错误码",
  message: "错误说明",
  category: "错误类型",
  retryable: "可以重试",
  operator_action: "处理建议",
  trace_id: "Trace ID",
  gate_id: "Gate ID",
  reason: "触发原因",
  risk_level: "风险等级",
  requested_action: "待执行操作",
  requested_by: "发起人",
  expires_at: "过期时间",
  decision: "处理结果",
  user: "调用身份",
  id: "标识",
  organization: "组织",
  roles: "角色",
  version_bundle: "版本组合",
  replay_id: "回放 ID",
  total: "用例数",
  passed: "通过数",
  failed: "失败数",
};

const wideConfigSections = new Set([
  "starters",
  "runtime",
  "stores",
  "model",
  "embedding",
  "prompt",
  "rag",
  "outbox",
]);

interface ConfigTabDefinition {
  id: string;
  label: string;
  keys: readonly string[];
}

const configTabDefinitions: readonly ConfigTabDefinition[] = [
  {
    id: "foundation",
    label: "基础与运行",
    keys: ["application", "profile", "starters", "runtime"],
  },
  {
    id: "ai",
    label: "模型与流程",
    keys: ["model", "embedding", "prompt", "rag", "workflow", "context", "policy"],
  },
  {
    id: "data",
    label: "数据存储",
    keys: ["stores"],
  },
  {
    id: "services",
    label: "缓存与事件",
    keys: ["redis", "cache", "rate_limit", "outbox"],
  },
  {
    id: "testing",
    label: "测试",
    keys: ["evaluation"],
  },
];

export function fieldLabel(path: string): string {
  const key = path.split(".").at(-1) ?? path;
  return labels[path] ?? labels[key] ?? key.replaceAll("_", " ");
}

export function ConfigForm({
  value,
  origins = {},
}: {
  value: DataRecord;
  origins?: DataRecord;
}) {
  const sections = Object.entries(value);
  const knownKeys = new Set<string>(
    configTabDefinitions.flatMap((tab) => [...tab.keys]),
  );
  const extraKeys = sections.map(([key]) => key).filter((key) => !knownKeys.has(key));
  const availableTabs = [
    ...configTabDefinitions.filter((tab) =>
      tab.keys.some((key) => Object.hasOwn(value, key)),
    ),
    ...(extraKeys.length
      ? [{ id: "other", label: "其他", keys: extraKeys }]
      : []),
  ];
  const [selectedTab, setSelectedTab] = useState(availableTabs[0]?.id ?? "");
  const activeTab =
    availableTabs.find((tab) => tab.id === selectedTab) ?? availableTabs[0];
  const visibleSections = sections.filter(([key]) => activeTab?.keys.includes(key));
  if (!sections.length) {
    return <p className="empty-copy">暂无配置。</p>;
  }
  return (
    <div className="config-workspace read-only">
      <div className="config-tabs" role="tablist" aria-label="配置分类">
        {availableTabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab?.id === tab.id}
            className={activeTab?.id === tab.id ? "active" : ""}
            onClick={() => setSelectedTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div
        className="config-form"
        role="tabpanel"
        aria-label={activeTab?.label}
      >
        {visibleSections.map(([key, sectionValue]) => (
          <section
            className={`config-section ${
              wideConfigSections.has(key) ? "wide" : ""
            }`}
            key={key}
          >
            <h3>{fieldLabel(key)}</h3>
            <div className="config-fields">
              <ConfigNode
                path={[key]}
                value={sectionValue}
                origins={origins}
              />
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function ConfigNode({
  path,
  value,
  origins,
}: {
  path: string[];
  value: unknown;
  origins: DataRecord;
}) {
  if (isRecord(value)) {
    return (
      <>
        {Object.entries(value).map(([key, nested]) => {
          const nestedPath = [...path, key];
          if (isRecord(nested)) {
            return (
              <fieldset className="config-subsection" key={key}>
                <legend>{fieldLabel(nestedPath.join("."))}</legend>
                <ConfigNode
                  path={nestedPath}
                  value={nested}
                  origins={origins}
                />
              </fieldset>
            );
          }
          return (
            <ConfigField
              key={key}
              path={nestedPath}
              value={nested}
              origins={origins}
            />
          );
        })}
      </>
    );
  }
  return (
    <ConfigField
      path={path}
      value={value}
      origins={origins}
    />
  );
}

function ConfigField({
  path,
  value,
  origins,
}: {
  path: string[];
  value: unknown;
  origins: DataRecord;
}) {
  const key = path.join(".");
  if (Array.isArray(value)) {
    return (
      <div className="form-field wide">
        <FieldTitle path={key} origin={origins[key]} />
        <ValueList values={value} />
      </div>
    );
  }
  if (typeof value === "boolean") {
    return (
      <label className="form-field toggle-field">
        <FieldTitle path={key} origin={origins[key]} />
        <input
          type="checkbox"
          checked={value}
          disabled
          readOnly
        />
        <em>{value ? "开启" : "关闭"}</em>
      </label>
    );
  }
  return (
    <label className="form-field">
      <FieldTitle path={key} origin={origins[key]} />
      <input
        type={typeof value === "number" ? "number" : "text"}
        value={value === null || value === undefined ? "" : String(value)}
        readOnly
        placeholder={value === null ? "使用默认值" : undefined}
      />
    </label>
  );
}

function FieldTitle({ path, origin }: { path: string; origin: unknown }) {
  return (
    <span>
      <span>{fieldLabel(path)}</span>
      {typeof origin === "string" && (
        <em className="field-origin">{originLabel(origin)}</em>
      )}
    </span>
  );
}

function originLabel(value: string) {
  return (
    {
      default: "框架默认",
      starter_default: "Starter 默认",
      yaml: "gaia.yaml",
      profile: "Profile",
      environment: "环境变量",
      cli: "CLI 覆盖",
    }[value] ?? value
  );
}

export function StructuredView({
  value,
  empty = "暂无数据。",
}: {
  value: unknown;
  empty?: string;
}) {
  if (value === null || value === undefined) {
    return <p className="empty-copy">{empty}</p>;
  }
  if (!isRecord(value)) {
    return <span>{displayValue(value)}</span>;
  }
  const entries = Object.entries(value);
  if (!entries.length) {
    return <p className="empty-copy">{empty}</p>;
  }
  return (
    <div className="structured-view">
      {entries.map(([key, item]) => (
        <Fragment key={key}>
          {isRecord(item) ? (
            <section className="structured-group">
              <h3>{fieldLabel(key)}</h3>
              <StructuredView value={item} />
            </section>
          ) : (
            <div className="structured-field">
              <span>{fieldLabel(key)}</span>
              {Array.isArray(item) ? (
                <ValueList values={item} />
              ) : (
                <strong>{displayValue(item)}</strong>
              )}
            </div>
          )}
        </Fragment>
      ))}
    </div>
  );
}

function ValueList({ values }: { values: unknown[] }) {
  if (!values.length) return <strong>-</strong>;
  if (values.every((item) => !isRecord(item))) {
    return (
      <div className="value-list">
        {values.map((item, index) => (
          <span key={`${displayValue(item)}-${index}`}>{displayValue(item)}</span>
        ))}
      </div>
    );
  }
  return (
    <div className="object-list">
      {values.map((item, index) => (
        <StructuredView key={index} value={item} />
      ))}
    </div>
  );
}

export function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "string") {
    const translated =
      {
        started: "已启动",
        configured: "已配置",
        active: "已生效",
        draft: "草稿",
        validated: "已校验",
        pending: "等待处理",
        approved: "已批准",
        rejected: "已拒绝",
        completed: "已完成",
        succeeded: "成功",
        failed: "失败",
        received: "已接收",
        running: "执行中",
        waiting_human: "等待人工确认",
        blocked: "已阻断",
        degraded: "降级运行",
        cancelled: "已取消",
        mock: "本地模拟",
        sandbox: "沙箱",
        customer: "客户环境",
        disabled: "未启用",
        approval_required: "需要审批",
        enabled: "允许",
      }[value] ?? value;
    if (/^\d{4}-\d{2}-\d{2}T/.test(value)) {
      const parsed = new Date(value);
      if (!Number.isNaN(parsed.getTime())) return parsed.toLocaleString();
    }
    return translated;
  }
  return String(value);
}

function isRecord(value: unknown): value is DataRecord {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
