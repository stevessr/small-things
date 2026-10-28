# AgentOS Harness — 多 Agent Linux 运行时原型

**阶段：v0.4 · Git 分支：`harness` · 测试平台：Ubuntu / openEuler 24.03 LTS SP4。**

一个以 Linux 子进程、资源预算、动态 DAG、Host IPC 与可选 LayerFS 工作区为核心的 Agent Supervisor；另有浏览器 Harness UI 和 Rust GPUI 原生查看器。不是定制内核、生产级多租户沙箱或已验证的 GPU KV Cache 共享系统。

## 快速开始

```bash
git clone --branch harness https://github.com/stevessr/small-things.git
cd small-things/agentos

# 两条命令均不会执行 Agent 或启动 Docker
python3 -m agentos.doctor --backend host --ui web
python3 -m agentos.plan_lint examples/agent-declarations.json --format json

# 实际启动 Agent，运行时打开本机只读监控
python3 -m agentos.harness_run examples/agent-declarations.json \
  --port 8765 --open-browser
```

浏览器访问 `http://127.0.0.1:8765`，停止服务按 Ctrl+C。执行结果默认写入 `.agentos/last-report.json` 与 `.agentos/last-trace.jsonl`（下次执行会覆盖）。`--exit-after-run` 用于 CI。

仅运行 DAG 而不启动 UI：

```bash
python3 -m agentos.cli examples/demo.json \
  --report /tmp/agentos-report.json --trace /tmp/agentos-trace.jsonl
```

## 面向 OAR 的可验证基础能力

```bash
python3 -m agentos.capabilities --backend host --format json
python3 -m agentos.capabilities --backend layerfs --format json
# 运行中的只读 API：
# curl 'http://127.0.0.1:8765/api/records?limit=100'
```

Supervisor 事件新增连续 `seq`、`session_id` 和声明者 `agent_path`；`/api/records` 用完整 JSONL 的稀疏索引重放所有仍保留的事件，不受 2 MiB 尾窗限制；不完整、旋转或旧 Trace 返回 409，不伪造事件。具体参考 [OAR 设计取舍](docs/oar-comparison.md)。

## 已实现能力

| 项目 | 当前能力 |
| --- | --- |
| 任务运行 | `AgentSpec`、DAG、依赖失败传播、优先级、资源预约、超时/重试 |
| 自主声明 | Host Agent 经 Unix IPC 批量 `declare_tasks`；LayerFS Agent 通过唯一 Manifest 提交子任务 |
| Host 资源控制 | Linux RLIMIT/进程组，委派 cgroup v2 可选 |
| Agent 通信 | Host Unix Socket、跨租户拒绝、有界队列、SQLite/zlib 文本 Context |
| LayerFS | `@layerfs/agent` SDK 桥接、独立 Workspace、Commit 和 FC 非破坏性 fork 回退 |
| Web Harness UI | 本地只读 DAG/日志/时间线/FC/资源摘要，inotify→SSE 事件驱动 |
| GPUI 原生 | Wayland/X11 UI，SSE 推送、服务器状态缓存与每页最多 40 项的摘要传输、按需日志、显示器尺寸裁剪 |
| 验证 | Host/LayerFS 模拟协议测试、Ubuntu/openEuler CI、独立 GPUI Rust/编译 CI |

LayerFS 的预算字段尚未映射为 Docker cgroup 真实配额，Host IPC 未透传给 LayerFS 容器；真实 SDK+Docker/FUSE 实机集成测试还未完成。GPUI 目前只验证 Linux 编译和协议逻辑，不代表真实 Vulkan 图形会话已经测通。

## 文档导航

- [完整文档入口](docs/README.md)
- [配置 JSON 与动态任务声明 / IPC 协议](docs/configuration.md)、[JSON Schema](docs/agentos-plan.schema.json)
- [设计架构、状态机、后端差异](docs/architecture.md)
- [openEuler / Linux / Wayland 部署运行](docs/deployment.md)
- [Harness UI REST/SSE、Lazy Load、GPUI](docs/harness-ui.md)
- [LayerFS / FC 恢复与安全操作](docs/layerfs-fc.md)
- [测试矩阵、指标口径和 CI](docs/testing.md)
- [故障排查](docs/troubleshooting.md)
- [安全边界和未实现能力](docs/security.md)
- [GPUI 原生查看器独立说明](ui-gpui/README.md)

## 独立运行会话与复现

```bash
python3 -m agentos.harness_run examples/agent-declarations.json \
  --runs-root .agentos/runs --port 8765 --exit-after-run
python3 -m agentos.sessions list --root .agentos/runs
```

每次创建 0700 独立目录，写入 0600 报告、Trace 与 Manifest；支持 SHA-256 完整性校验，不会覆盖历史运行。参见 [会话保留和验证](docs/run-sessions.md)。

## 深入文档

- [贡献指南](CONTRIBUTING.md) · [API/事件规范](docs/api-reference.md) · [机器可读 OpenAPI](docs/openapi.json)
- [完整 Trace 语义](docs/trace-format.md) · [能力成熟度](docs/capabilities.md) · [OAR 设计对照](docs/oar-comparison.md)
- [可执行教程](docs/tutorials/README.md) · [ADR](docs/adr/README.md) · [实验复现模板](docs/reproducibility.md)

## 版本与验收

- [变更记录](CHANGELOG.md) · [发布/答辩检查清单](docs/release-checklist.md)

## 测试与开发

```bash
python3 -m unittest discover -s tests -v
python3 -m agentos.plan_lint examples/layerfs-demo.json
python3 -m bench.benchmark --tasks 6 --parallel 3 --sleep 0.05 --trials 2
```

详见 [Harness CI](https://github.com/stevessr/small-things/actions/workflows/agentos-harness.yml) / [GPUI CI](https://github.com/stevessr/small-things/actions/workflows/agentos-gpui.yml)。微基准只测合成调度，不等于真实 LLM token/s、KV Cache 复用率或端到端 Agent 产品性能。
