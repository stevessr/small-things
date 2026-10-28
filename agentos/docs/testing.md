# 测试、回归与实验记录

## 1. 开发者最短测试序列

在 `small-things/agentos/` 下执行：

```bash
python3 -m agentos.plan_lint examples/demo.json
python3 -m unittest discover -s tests -v
python3 -m agentos.cli examples/demo.json --report /tmp/agentos-report.json
python3 -m agentos.harness_run examples/agent-declarations.json \
  --port 0 --exit-after-run --report /tmp/declared-report.json \
  --trace /tmp/declared-trace.jsonl
python3 -m bench.benchmark --tasks 6 --parallel 3 --sleep 0.05 --trials 2
```

`--port 0` 让测试操作系统选择一个空闲本机端口；不适用于固定端口客户端的真实生产连接。最后一步只测合成 sleep 调度吞吐，不是 GPU/LLM 性能结果。

## 2. 测试矩阵与覆盖范围

| 测试 / Workflow | 覆盖点 | 明确没有覆盖的内容 |
| --- | --- | --- |
| `tests/test_runtime.py` | 任务状态机、DAG 依赖、重试超时、预算、Host IPC、失败传播、动态任务声明、跨租户拒绝 | 不可信 OS 沙箱、多机调度 |
| `tests/test_layerfs.py` + `tests/fake_layerfs.mjs` | 桥接协议、Commit 元数据、Manifest、FC history/rewind/files 的逻辑 | **真实 LayerFS SDK、Docker、daemon、FUSE** |
| `tests/test_harness_ui.py` | 本地 HTTP、Host 头、防目录穿越、inotify→SSE、只读 API、135 任务分页/非法范围/错误码、按需详情 | 真实浏览器像素截图、GPU 画面 |
| `tests/test_harness_runner.py` | 一键 Runner 的动态 DAG 执行、Report 与 Trace | 长期运行中的容灾和断电持久性 |
| `tests/test_record_index.py` | 超过 2 MiB / 4000 条的全历史分页、增量追加、半行、文件轮换、损坏、缺号、并发和 HTTP 回放 | 百万级文件首扫性能、强对抗同 UID 修改仍待验证 |
| `tests/test_record_stream.py` | 单调 seq、独立执行身份、嵌套 Agent 归属、HTTP 游标/断流/轮换/旧日志、Host IPC control request_id 与敏感数据剔除 | 第三方模型原生 token 和 tool-call 帧尚未实现 |
| `tests/test_capabilities.py` | Host/LayerFS 显式能力矩阵、typed rejection、执行前要求、无副作用探测 | 真实 Docker/FUSE/cgroup 是否可用需实机验证 |
| `tests/test_plan_lint.py` | 所有执行计划 JSON、循环/越权/重复/缺失依赖、只读 doctor、静态 CLI | 不启动真实 LayerFS Docker |
| `tests/test_docs.py` | 内部 Markdown 相对链接、配置样例、CLI 帮助命令存在性 | 外部网络链接存活性 |
| `.github/workflows/agentos-harness.yml` | Ubuntu + openEuler 运行上述单元/集成和 Host Demo | openEuler 裸机内核能力、委派的真实 cgroup |
| `.github/workflows/agentos-gpui.yml` | Linux GPUI Rust 模型测试、原生 `cargo check` | 实际 Wayland/X11 显示与 Vulkan 渲染 |

注意区分“模拟 LayerFS 协议通过”与“实机文件系统已验证”。CI 可以证明 Python 和 Rust 代码编译、纯用户态逻辑正确，不证明 sandbox 具有强隔离或 Store 具备掉电持久性。

新增 `tests/test_harness_runner.py` 的会话测试覆盖：互不覆盖的历史目录、0600/0700 权限、端口冲突不覆盖旧报告、失败任务记录、SHA-256 篡改检测。CLI `agentos.sessions` 支持只读列出/核验，见 [运行会话指南](run-sessions.md)。

## 3. 文档可执行性要求

修改 HTTP 端点或任务数据时，文档契约测试将对比 [OpenAPI](openapi.json) 与 [真实路由](../agentos/harness_ui.py)、[AgentResult](../agentos/models.py)；新增事件时会检查 [事件字典](trace-format.md) 与 Runtime `_event` 字面量。教程入口详见 [可执行教程](tutorials/README.md)，性能结论使用 [实验复现模板](reproducibility.md)。



- 每个 `examples/*.json` 中的执行计划都应能通过 `python3 -m agentos.plan_lint`；`examples/harness-ui-sample.json` 是**终局报告**，例外。
- 若新增 `AgentSpec` 字段，修改 `docs/configuration.md` 的字段表，并新增合法/拒绝示例。
- 若新增 CLI 操作，更新 `docs/deployment.md`、`docs/troubleshooting.md` 和测试的 `--help` smoke check。
- 修改 SSE/REST/GPUI 时更新 `docs/harness-ui.md`，明确是否多了网络调用与状态轮询。
- 更改 LayerFS 分支或 FC 语义时更新 `docs/layerfs-fc.md`，不要描述为“原地回滚”。
- 文档命令默认在 `agentos/` 目录执行；需要目录切换必须写清楚。

## 4. 故障注入与手动真实环境检查清单

可重复的人工检查案例：

1. Host：任务 exit code 非 0 → 下游 `BLOCKED`，无关分支继续执行。
2. Host：重试耗尽/超时 → 子进程组被回收、未泄漏资源槽位。
3. IPC：声明一批重复 ID、未知依赖或环 → 整批不准入。
4. UI：先启动监控、再启动任务 → 自动通过 SSE 刷新；断开 SSE 时保留手动刷新。
5. UI：报告先以临时文件写入再 `rename` 到目标 → 监控收到 `MOVED_TO` 通知。
6. GPUI：Wayland 4K/低 DPI/双屏场景 → 初始窗口不超过目标屏幕可见尺寸；每页最多 40 项。
7. LayerFS 实机：成功 Commit、失败 discard、同一文件的并行冲突、指定 Commit fork、选文件恢复。
8. 安全：跨租户 IPC/依赖拒绝，任意路径/Host Header 测试返回拒绝结果。
9. 压测：长链（大于 1,000 节点）拓扑检测不递归；观察 JSON 报告体积上限、Trace 截断效果。

第 6、7 项需要**实际图形会话 / Docker/FUSE 环境**。不要把测试替身通过当作硬件验证。

## 5. 评测建议与指标口径

至少记录：Git commit SHA、Linux 发行版与内核、CPU/GPU、Python/Node/Rust 版本、任务 DAG、并发 CPU/memory 配额、上下文存储方式、预热条件及样本数量。对于时间指标，按多次重复运行计算 p50、p95、均值/中位数、方差或置信区间。固定同一输入、相同失败率后比较串行、Host 并行、Host+Context（只读缓存命中）、实际 LayerFS 等场景。

若声称是“系统级多 Agent 优势”，必须注明代理的是**进程层任务管理与文件历史**。现有 `bench.benchmark` 的 sleep work 只能展示调度并发，不能说明 token/s、GPU KV、真实模型推理加速或节省显存。

## 6. CI 失败快速定位

每轮改动的最终验收使用 [发布检查清单](release-checklist.md)。CI 通过只证明相应测试覆盖的功能，不代替 LayerFS/Docker/FUSE 实机和真实 Wayland/Vulkan 会话验证。



查看 [Harness CI](https://github.com/stevessr/small-things/actions/workflows/agentos-harness.yml) 和 [GPUI CI](https://github.com/stevessr/small-things/actions/workflows/agentos-gpui.yml)：

- Python 单测失败：先看失败的测试方法，修复后执行整套 `unittest discover`。
- Host Demo 失败但单测通过：检查 `cli.py`、`harness_run.py` 是否引用失效变量、运行路径、导入路径。
- openEuler 安装依赖慢：区分镜像下载 / dnf 超时与项目回归失败，避免把基础设施异常解释为功能失败。
- GPUI 编译失败：先看 `gpui-pre` 版本、Rust toolchain、`id(...)`、字体/布局 API，再跑 `cargo check --features desktop`。
