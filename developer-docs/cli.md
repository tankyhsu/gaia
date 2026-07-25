# 命令行参考

## 项目与开发

| 命令 | 作用 |
| --- | --- |
| `gaia init <directory>` | 创建独立 Gaia 应用 |
| `gaia add-workflow <name>` | 增加应用自有 Workflow 和路由测试 |
| `gaia dev` | 加载应用并启动 ASGI 服务 |
| `gaia starters` | 列出内置 Starter 和装配条件 |

常用初始化参数：

```bash
gaia init my-app \
  --name my-app \
  --template knowledge \
  --component prompt-registry
```

- `--template`：`basic`、`knowledge` 或 `approval`。
- `--component`：使用容易识别的能力名称按需激活组件。
- `--starter`：高级入口，直接指定底层 Starter。

开发模式热重载：

```bash
gaia dev --config gaia.yaml --app my_app.app:app --reload
```

配置文件路径按以下顺序选择：

1. 命令行 `--config`；
2. 环境变量 `GAIA_CONFIG_PATH`；
3. 当前目录的 `gaia.yaml`。

旧 `GAIA_CONFIG` 暂时兼容，但会提示迁移到 `GAIA_CONFIG_PATH`。`gaia dev --app ... --reload`
会把最终配置路径传递给 Uvicorn 子进程，应用入口和 CLI 始终加载同一文件。

## 检查与诊断

```bash
gaia check --config gaia.yaml
gaia doctor --config gaia.yaml --profile sandbox
gaia migrate --config gaia.yaml
```

- `check` 只检查配置、依赖展开和自动装配，不连接外部系统。
- `doctor` 主动探测数据库、Redis、模型和 Embedding Endpoint。
- `migrate` 更新 Gaia 拥有的 operational schema。

`--profile` 是切换 `gaia.yaml` Profile 的正式入口。其他临时配置仍通过 `--set` 覆盖：

```bash
gaia check \
  --config gaia.yaml \
  --profile sandbox \
  --set runtime.write_mode=approval_required
```

Profile 在应用启动时确定。Gaia 不支持在运行中的进程内热切换 Profile。

## AI 应用测试

应用提供一个返回 `GaiaTestKit` 的工厂后，可以直接运行版本化 Dataset：

```bash
gaia test tests/datasets/release-golden.yaml \
  --kit tests.eval:create_kit \
  --repetitions 3 \
  --subject revision=abc123 \
  --output reports/release.json
```

门禁全部通过时退出码为 `0`，质量门禁未通过时为 `1`，Dataset 或工厂无法加载时为 `2`。
报告同时输出到标准输出；指定 `--output` 后也会写入文件。

## Prompt 生命周期

```bash
gaia prompt import prompts/summary/1.0.0.yaml \
  --config gaia.yaml --actor developer

gaia prompt validate summary 1.0.0 \
  --report reports/summary-1.0.0.json \
  --config gaia.yaml --actor qa

gaia prompt publish summary 1.0.0 \
  --environment sandbox \
  --config gaia.yaml --actor release-manager

gaia prompt rollback summary 1.0.0 \
  --environment sandbox \
  --config gaia.yaml --actor release-manager
```

查看当前安装版本的精确参数：

```bash
gaia --help
gaia <command> --help
```
