# 从其他语言接入

**Gaia 不提供手写的 Client SDK。**

这里的 Client SDK 指其他进程或其他语言调用 Gaia HTTP API 的客户端。Python 应用作者使用的是
`gaia` 顶层编写 API；扩展作者使用 `gaia.spi` 协议，它们与 HTTP Client SDK 不是一回事。

曾经有一个 TypeScript 包，删掉了。它六个方法里五个是十行 `fetch`；唯一有内容的那个
（SSE 消费）没有任何人用；而它作为 OpenAPI schema 的第二份手写副本，还需要一个专门的检查器
盯着自己不漂移——给 `RunSnapshot` 加一个字段就得同步改它，漏改一次要靠门禁才发现。

**接口契约是 `specs/openapi.json`**，由 FastAPI 从代码生成，`make contracts` 检查它不与代码
漂移。类型用 OpenAPI Generator、`openapi-typescript`、`datamodel-code-generator` 之类的工具
生成，不要手抄。调用本身用你那门语言自带的 HTTP 客户端就够了。

下面两件事是读 OpenAPI 看不出来、又容易出错的。

## 创建 Run 必须带 `Idempotency-Key`

`POST /v1/runs` 要求这个头。**没有它，一次网络重试会创建出第二个 Run**，而不是拿回第一个。

```ts
await fetch("/v1/runs", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-Gaia-Api-Key": apiKey,
    "Idempotency-Key": crypto.randomUUID(),
  },
  body: JSON.stringify({
    scenario_id: "refund.request",
    mode: "mock",
    user: { id: "u-1", organization: "acme", roles: ["employee"] },
    request: { text: "客户要求全额退款" },
  }),
});
```

同一个 key 重放会返回同一个 Run。换了请求体还用同一个 key，Gaia 返回
`IDEMPOTENCY_CONFLICT`，而不是悄悄接受其中一个。

## 订阅进度用 SSE，不要轮询

`GET /v1/runs/{run_id}/events/stream` 是 Server-Sent Events。

```ts
const stream = await fetch(`/v1/runs/${runId}/events/stream`, {
  headers: { "X-Gaia-Api-Key": apiKey },
});
const reader = stream.body!.pipeThrough(new TextDecoderStream()).getReader();
for (;;) {
  const { value, done } = await reader.read();
  if (done) break;
  for (const line of value.split("\n")) {
    if (line.startsWith("data: ")) handle(JSON.parse(line.slice(6)));
  }
}
```

## 客户端不承担控制

生成的类型和上面的代码只负责协议。**Policy、角色校验、写入边界、人工审批全部在服务端强制。**

调用方不需要、也不应该复制这些规则：复制出来的那一份既拦不住绕过你这个前端的调用，又会和
服务端的真实策略分家——而分家的表现形式，是界面开始对用户说一件服务端并不同意的事。客户端
要做的只有一件：把服务端返回的拒绝如实呈现出来。

认证、身份来源和跨组织隔离的规则见 [HTTP 认证与授权](http-api.md)。
