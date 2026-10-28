# 可执行教程

三条教程按 **Host 动态 DAG → 事件观测 → LayerFS FC** 的顺序编排。默认目录 `small-things/agentos/`。示例只使用仓库已存在的执行计划与代码，不依赖尚未实现的 GUI 回退按钮。

| 教程 | 先决条件 | 执行行为 |
| --- | --- | --- |
| [01 Host 动态 DAG](01-host-dynamic-dag.md) | Python 3.11+ / Linux | **会执行**受信的 Python Demo 子进程 |
| [02 事件驱动 UI](02-event-driven-ui.md) | Linux / Python 3.11+；可选 GPUI | 会创建本机 HTTP 服务、Report、Trace |
| [03 LayerFS/FC](03-layerfs-fc.md) | 外部 LayerFS SDK + daemon + Docker | **会创建 LayerFS 项目/分支与 Workspace**，仅在按说明配置后执行 |

环境预检与 Plan 检查是只读的；`agentos.cli`、`agentos.harness_run`、`agentos.layerfs_init` 和 FC 恢复命令会真正修改进程、文件或 LayerFS 状态。

相关参考：[部署指南](../deployment.md)、[配置协议](../configuration.md)、[测试与复现](../reproducibility.md)。
