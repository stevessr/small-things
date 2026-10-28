# 能力成熟度与兼容性边界

本表为 `harness` 分支 v0.4 的实际实现范围。**支持**代表代码路径存在，**模拟验证**代表只用 SDK 替身而非真实外部系统，**待实现**不应出现在使用指南的可执行承诺中。

| 能力 | 状态 | 证据与限制 |
| --- | --- | --- |
| Host 多 Agent DAG、优先级和资源预约 | 已实现，CI 验证 | `tests/test_runtime.py` |
| 动态批量任务声明、租户/环校验 | 已实现，CI 验证 | `tests/test_runtime.py`、`tests/test_plan_lint.py` |
| Linux Host RLIMIT/进程组回收 | 已实现，CI 验证 | 非安全沙箱；`RLIMIT` 只是故障隔离 |
| Host cgroup v2 CPU/memory/pids | 有代码路径，需管理员委派实机 | CI 不验证强隔离；存在 attach 时间窗 |
| Host Unix IPC + SQLite/zlib 文本 Context | 已实现，CI 验证 | 无 GPU KV Cache |
| LayerFS Node SDK 的分支/Workspace/FC | 模拟 SDK 协议验证 | 无真实 Docker/FUSE 端到端 CI |
| LayerFS Manifest 动态声明 | 模拟 SDK 协议验证 | 单任务 Commit 后纳管 |
| LayerFS FC 回退 | 模拟 SDK 协议验证 | 只 fork 新分支，不回滚 API/DB/邮件副作用 |
| LayerFS Docker cgroup 真配额 | 待实现 | 预算目前仅为调度控制面预约 |
| Host IPC 透传至 LayerFS Docker | 待实现 | Host 的 `send/recv/context` 不可直接跨 Docker 使用 |
| Web DAG/日志/FC UI | 已实现，HTTP+测试覆盖 | 只读、localhost、非公网服务 |
| Linux inotify → SSE | 已实现，CI 验证 | 非 Linux/文件父目录不匹配时可能无法监听 |
| 原生 GPUI Lazy Load 和 40 项分页 | Rust 测试与编译通过 | 没有实机 Wayland/Vulkan 截图验证 |
| GPUI 连续 GPU CPU/RSS 曲线 | 待实现 | Report 当前主要返回终局指标 |
| GPU KV Cache 跨模型共享 | 未实现 | 不能从 SQLite 文本缓存推导 |
| 原生内核调度器 / 多节点 / mTLS | 未实现 | 非目标阶段 |

## 接口兼容范围

- **Plan**：严格顶层 `budget` + `tasks`，任务字段以 `AgentSpec` 为准；更新字段需同步 [JSON Schema](agentos-plan.schema.json) 和 [配置文档](configuration.md)。
- **Trace**：`time_ns` + `event` + 事件自有字段；参见 [事件格式](trace-format.md)，现阶段没有独立事件版本号。
- **Report**：完整 Host Runtime 结果；**没有统一的独立版本字段**。
- **HTTP UI**：`schema=1`；[OpenAPI](openapi.json) 描述路径与主要数据结构，可能在 v0.4 原型中变化。
- **FC**：以 LayerFS 的不可变 Commit 和新 Branch 作为安全操作边界，历史查询与回退命令没有实现跨 SDK 版本迁移。
- **GPUI**：对应当前 Harness v0.4 的 HTTP 传输，已做增量读取但不保证任意版本互操作。

## 何时可以宣称“可用于生产”

至少还需独立受限 UID/namespace、rootless 运行和密钥隔离、真实容器配额、持久化任务调度元数据、任务幂等/补偿事务、跨机器认证、日志轮转与审计、LayerFS 实机故障注入和安全审计、GPUI 实机测试。这是未来验收清单，不是本次提交已经具备的能力。
