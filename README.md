# small-things

这里包含若干独立脚本与实验项目；`harness` 分支中的 **AgentOS Harness** 是独立的 Linux/openEuler 多 Agent 运行时原型，不影响仓库其他脚本。

## AgentOS Harness v0.4

- [项目介绍与快速开始](agentos/README.md)
- [完整文档导航](agentos/docs/README.md)
- [任务计划与动态 DAG / IPC](agentos/docs/configuration.md)
- [JSON Schema 配置字段提示](agentos/docs/agentos-plan.schema.json)
- [openEuler、Linux、Wayland 部署](agentos/docs/deployment.md)
- [Web/GPUI UI 与事件驱动 SSE](agentos/docs/harness-ui.md)
- [LayerFS 与 FC 回退](agentos/docs/layerfs-fc.md)
- [测试与 CI](agentos/docs/testing.md)
- [排查指南](agentos/docs/troubleshooting.md)
- [安全边界](agentos/docs/security.md)

其他入口：[贡献指南](agentos/CONTRIBUTING.md)、[API/OpenAPI](agentos/docs/api-reference.md)、[事件格式](agentos/docs/trace-format.md)、[教程](agentos/docs/tutorials/README.md)、[实验模板](agentos/docs/reproducibility.md)。

版本信息：[AgentOS Changelog](agentos/CHANGELOG.md) · [发布/演示验收清单](agentos/docs/release-checklist.md)。

最小预检：

```bash
cd agentos
python3 -m agentos.plan_lint examples/agent-declarations.json
python3 -m agentos.doctor --backend host --ui web
```

`harness` 是开发分支。真实 LayerFS Docker/FUSE 与完整 Wayland 图形交互尚未达到可声明已验证的程度；详情见文档中的测试覆盖与限制。
