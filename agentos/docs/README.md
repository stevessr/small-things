# AgentOS Harness 文档导航

适用分支：`harness`；版本定位：**v0.4 原型**。路径均相对 `small-things/agentos/`。文档描述现有代码而不是路线图上的功能。

| 场景 | 文档 |
| --- | --- |
| 先启动一次任务 / 打开监控 | [项目 README](../README.md)、[部署与运行](deployment.md) |
| 编写 DAG / 动态声明任务 | [计划与协议参考](configuration.md)、[JSON Schema](agentos-plan.schema.json) |
| 了解架构和状态机 | [架构与数据流](architecture.md) |
| 使用 Web UI / GPUI / SSE | [Harness UI 协议与运维](harness-ui.md)、[GPUI 专项](../ui-gpui/README.md) |
| 安装 LayerFS、查历史、FC 文件回退 | [LayerFS + FC](layerfs-fc.md) |
| 重现 CI、测试、故障注入和指标口径 | [测试与评估](testing.md) |
| 运行失败 / 空白监控 / GPU 问题 | [排障手册](troubleshooting.md) |
| 威胁模型与生产化缺口 | [安全与实现边界](security.md) |

## 最短验证路径

```bash
git clone --branch harness https://github.com/stevessr/small-things.git
cd small-things/agentos
python3 -m agentos.doctor --backend host --ui web
python3 -m agentos.plan_lint examples/agent-declarations.json --format json
python3 -m unittest discover -s tests -v
python3 -m agentos.harness_run examples/agent-declarations.json --port 8765 --open-browser
```

最后一条会实际运行示例 Agent；前两条**只读且不会执行任务**。Web 界面只绑定 `127.0.0.1`。需要结束持续提供界面的进程，按 `Ctrl+C`。

## 后端能力速查

| 能力 | Host subprocess | LayerFS Docker |
| --- | --- | --- |
| 静态 DAG / 资源预约 | 支持 | 支持（逻辑预约） |
| Agent 在运行中声明依赖 | Unix Socket `declare_tasks` / `spawn` | 任务唯一 Manifest，成功 Commit 后纳管 |
| 跨 Agent 文件继承 / merge | 不提供 Workspace 分支隔离 | LayerFS Branch / Merge |
| FC 文件树检查点 | 无 | 每任务成功时 Commit |
| FC 非破坏性回退 | 无 | `history`、`rewind`、`files` |
| 宿主 cgroup v2 强制配额 | 可选、需管理员委派 | 尚未接入 AgentOS cgroup 配额 |
| `send/recv` 与 SQLite Context | Host IPC | 尚未透传至 Docker |
| GPU KV Cache 共享 | 未实现 | 未实现 |
| 真实 Docker/FUSE 集成 CI | 不适用 | **尚未实现**：目前使用假 SDK |

## 文档质量约束

配置键以 `agentos/models.py` 为准，运行 CLI 以模块 `--help` 为准。运行命令从 `agentos/` 目录执行。文档示例的 JSON 配置须通过 `agentos.plan_lint`，CI 验证文档相对链接与主要示例。新增功能时需要同步更新协议、限制、测试与已知缺口。
