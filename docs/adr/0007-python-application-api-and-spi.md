# ADR 0007：顶层 Python 应用 API 与独立 SPI

## 状态

Accepted — 2026-08-02

## 背景

Gaia 已删除手写的 HTTP Client SDK，外部调用方应从 OpenAPI 生成类型并使用标准 HTTP 客户端。
仓库里仍存在 `gaia.sdk`，但它混合了三类不同职责：应用编写 DSL、扩展协议和具体实现。这既会让
使用者误以为 Client SDK 仍然存在，也使文档同时推荐 `gaia` 与 `gaia.sdk` 两套公共入口。

## 决策

- 应用作者只从 `gaia` 顶层导入 Scenario、Tool、Handoff、Continuation 和版本指纹等编写 API。
- 扩展作者从 `gaia.spi` 导入 Model、Prompt、RAG、Auth、Cache、Event、Memory 和 Tool 协议及其
  协议数据类型。
- `gaia.spi` 不包含具体实现，也不依赖 Runtime、Persistence、Integration、Starter 或 API 层。
- `ApiKeyAuthnProvider`、`InProcessEventPublisher` 等具体实现归入 `gaia.integrations`。
- 删除 `gaia.sdk`，不保留第二套兼容导入路径。项目仍处于 `0.1.0`，此时直接收敛公共面比长期
  保留含混命名更安全。

## 示例

```python
from gaia import ScenarioContext, ScenarioResponse, scenario, write_tool
from gaia.spi import AuthnProvider, ModelProvider, Retriever
from gaia.integrations import ApiKeyAuthnProvider
```

## 后果

生成项目、参考应用与 Python 文档必须只展示顶层应用 API；只有实现自定义适配器的内容才展示
`gaia.spi`。架构测试检查 SPI 依赖方向和类形态，并明确断言旧 `gaia.sdk` 包不存在。
