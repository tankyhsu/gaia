# controlled-task 验收夹具

这个目录保留 Gaia 早期的合成业务，用于回归 Runtime 的完整安全与恢复语义。它覆盖合法读取、
参数拒绝、跨组织拒绝、证据不足、执行前 HumanGate、人工拒绝、副作用结果未知、幂等和等待期间
重启恢复等固定案例。

它不是 Gaia 的公共任务类型、应用开发 API 或产品 Showcase：

- Gaia wheel 不打包 `examples/`；
- `src/gaia/`、OpenAPI、Docker 默认命令、日常开发入口和部署模板都不得依赖本目录；
- 新应用从 `examples/function_task/` 或 `gaia init` 开始；
- 真实业务演示由仓库外的 HR Showcase 通过 Gaia 公共扩展点接入。

只有验收测试可以把这里的固定资源、组织、规则和 Mock Adapter 当作测试事实。若公共 Runtime
契约改变，应同步更新测试；不要为了让其他入口启动而重新把这个应用装进框架交付物。
