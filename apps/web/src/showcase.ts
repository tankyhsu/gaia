// The HR reference application. It is a separate project outside this repo
// (`../showcase/gaia-hr-suite`); `make demo` starts it, and tells the Console
// whether it actually came up so these are rendered as links only when
// something is listening.
export const SHOWCASE_URL =
  import.meta.env.VITE_GAIA_SHOWCASE_URL ||
  (location.port === "4181"
    ? `${location.origin}/hr/`
    : `${location.protocol}//${location.hostname}:4173/`);

export const SHOWCASE_UNAVAILABLE =
  import.meta.env.VITE_GAIA_SHOWCASE_UNAVAILABLE === "true";

export const SHOWCASE_EXAMPLES = [
  {
    name: "入职权限开通",
    description: "模型生成权限草案，规则校验后由 IT 确认，再逐项写入多个系统。",
    path: "#onboarding",
  },
  {
    name: "员工政策与个人假期问答",
    description: "组合员工手册检索、当前员工身份和 HR 数据，生成有依据的个性化回答。",
    path: "#handbook",
  },
  {
    name: "请假办理",
    description: "模型理解自然语言申请，校验余额和规则，经理批准后才写入 HR 系统。",
    path: "#leave",
  },
] as const;
