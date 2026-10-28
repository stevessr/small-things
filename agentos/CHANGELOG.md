# AgentOS Harness 变更记录

本文件记录 `harness` 分支的主要阶段。该分支仍是开发原型，当前 `pyproject.toml` 版本为 **0.4.0**；以下是功能阶段摘要，不意味着仓库已经发布正式的稳定版制品。

## v0.4 · Harness UI、事件驱动 GPUI、文档契约

- 本机只读 Web Harness UI，DAG、任务状态、日志、FC 元数据及时间线。
- Linux inotify → SSE 通知；GPUI Rust 原生查看器采用按需任务详情、每页最多 40 个任务、显示器裁剪尺寸。
- 参考 [botiverse/oar](https://github.com/botiverse/oar) 的事实顺序/归属与能力边界，加入 `seq/session_id/agent_path`、严格 `/api/records` 游标、认证后的 IPC 控制处理记录及显式后端能力拒绝。
- 新增 `--runs-root` 独立运行会话、原子终局文件与 0600/0700 权限、报告/Trace SHA-256 校验、只读 `agentos.sessions` 历史查询。
- `harness_run` 一键运行 + 观察；`plan_lint` 无副作用计划预检；`doctor` 无副作用环境诊断。
- 完整中文文档：架构、配置、LayerFS/FC、部署、API/OpenAPI 3.1、Trace、事件、测试、实验复现、教程、贡献与 ADR。
- CI 覆盖 Ubuntu、openEuler 和独立 GPUI 原生编译；真实 Vulkan/Wayland 会话与 LayerFS Docker/FUSE 仍未实现实机验证。

## v0.3 · Agent 动态 DAG 纳管

- `declare_tasks` 批量声明子任务，自动父依赖、同批依赖、租户/预算/环校验。
- Host IPC 和 LayerFS Workspace Manifest 两条纳管路径。
- 修复失败后 `BLOCKED` 沿长链的传播，静态图改为非递归拓扑检测。
- 报告增加 `dag` 与 `declared_by`。

## v0.2 · LayerFS + FC

- JS SDK 桥接、LayerFS 独立 Branch/Workspace/Commit。
- FC history、rewind、files；恢复只建立新 Branch，保留来源状态。
- 模拟 SDK 的协议测试，不代表真实 Docker/FUSE 端到端已验证。

## v0.1 · Host 多 Agent 执行器

- AgentSpec/Budget、依赖 DAG、生命周期、优先级与资源预约。
- Linux 子进程/进程组、RLIMIT、可选 cgroup v2。
- Unix Domain Socket IPC、SQLite/zlib 文本上下文和合成调度基准。

## 版本约束

`agentos/docs/openapi.json` 的 `info.version` 与 Python 包当前版本保持一致；HTTP `schema=1` 只是监控数据格式号。Plan 字段以 `AgentSpec` 和 JSON Schema 为准；Trace/Report 未加入独立版本号。版本升级应同步修改 [贡献指南](CONTRIBUTING.md)、[能力矩阵](docs/capabilities.md)、[实验复现](docs/reproducibility.md) 和 [发布检查清单](docs/release-checklist.md)。
