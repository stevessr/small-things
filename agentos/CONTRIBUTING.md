# 为 AgentOS Harness 贡献代码与文档

工作分支：`harness`。AgentOS 位于仓库独立的 `agentos/` 目录，其他脚本与目录不在此子项目范围内。本文以 openEuler / Linux 用户态多 Agent Runtime 的工程可复现性为准则。

## 1. 开发环境

- Python **3.11+**，核心无第三方 Python 运行时依赖；
- Node.js **20+** 仅用于 LayerFS JS 桥接模拟测试及真实 LayerFS 后端；
- GPUI 独立前端需要 Rust stable 和 Linux Wayland/X11/Vulkan 开发依赖；
- 默认 Host 测试在 Linux 用户态运行，普通 CI 不需要 Docker。

```bash
git clone -b harness https://github.com/stevessr/small-things.git
cd small-things/agentos
python3 -m agentos.plan_lint examples/demo.json
python3 -m agentos.doctor --backend host --ui web
python3 -m unittest discover -s tests -v
node --check agentos/layerfs_bridge.mjs
node --check agentos/ui/app.js
```

增量开发使用小范围提交，明确模块与目的。例如 `docs(agentos): ...`、`test(harness): ...`、`fix(gpui): ...`。合并 `main` 前单独确认；不要把改动直接夹进 unrelated scripts。

## 2. 文档与代码同步规则

| 变化 | 必须同步的文档与测试 |
| --- | --- |
| 增减 `AgentSpec`、`Budget` 字段 | `docs/configuration.md`、`docs/agentos-plan.schema.json`、`test_docs.py` |
| 新增 Broker `op` | `docs/configuration.md`（IPC 表）、`tests/test_runtime.py` |
| 新增/修改生命周期事件 | `docs/trace-format.md`、`tests/test_docs.py`、Web/GPUI UI 消费端 |
| 新增本机 HTTP 端点/字段 | `docs/openapi.json`、`docs/api-reference.md`、`tests/test_harness_ui.py` |
| 修改 inotify/SSE/GPUI | `docs/harness-ui.md`、`ui-gpui/README.md`，标注是否引入定时数据轮询 |
| 修改 LayerFS Branch/FC 语义 | `docs/layerfs-fc.md`、`tests/test_layerfs.py`；保留不可变来源 |
| 修改预算/cgroup/隔离 | `docs/security.md`、`docs/deployment.md`，并给出真实 OS 层证据 |
| 调整安装入口或 CLI | `docs/deployment.md`、`docs/troubleshooting.md`、`tests/test_docs.py` |
| 修改基准或统计 | `docs/reproducibility.md`、`docs/testing.md`，不得混淆合成 workload 与 LLM |

## 3. 如何写可复现问题

提交 Issue/PR 时提供：Git SHA、OS/内核、Python/Node/Rust 版本、运行命令（去除秘密）、最小 Plan JSON、完整报错、实际状态/预期状态；涉及 LayerFS 时附上 SDK/daemon/Docker 版本、是否真实 Store 与 FUSE；涉及 GPUI 时附 Wayland/X11、分辨率缩放、Vulkan 驱动与是否多屏。

若涉及安全漏洞或私钥，请不要公开真实 token/环境文件或完整敏感 Trace。

## 4. PR 检查清单

- [ ] 新增任务字段/端点/事件时同步了机器可读契约与文档。
- [ ] 新增行为具有正向和失败/拒绝路径的测试。
- [ ] 已运行 `python3 -m unittest discover -s tests -v`。
- [ ] 若修改 Rust：已运行 `cargo test --no-default-features` 和 `cargo check --features desktop`。
- [ ] 文档示例从 `agentos/` 工作目录可以执行，文件路径/链接有效。
- [ ] 未把 Fake LayerFS SDK 当成真实 Docker/FUSE 验证。
- [ ] 未增加 GPUI 固定频率状态轮询；窗口尺寸与 40 个任务分页约束保持。
- [ ] 未增加公开写接口或未经授权的 destructive FC 回退。
- [ ] CI Ubuntu/openEuler/GPUI 相关任务已通过，或明确记录环境限制。
