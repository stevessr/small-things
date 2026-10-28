# AgentOS Harness 发布与演示验收清单

适用范围：`harness` 分支原型验证或竞赛演示。它**不是**证明已达到生产就绪或通过安全审计的认证流程。

## A. 配置和契约

- [ ] `python3 -m agentos.plan_lint examples/demo.json` 返回 0，所有 Plan 示例通过静态校验。
- [ ] `python3 -m agentos.doctor --backend host --ui web` 通过，没有忽略任何 `fail` 条目。
- [ ] `AgentSpec`、`Budget` 字段与 `agentos-plan.schema.json` 一致。
- [ ] HTTP API 路由、状态字段和事件名与 `openapi.json`、`trace-format.md` 一致。
- [ ] `CHANGELOG.md`、`docs/capabilities.md` 标注已验证和仍未完成的能力。

## B. Host 与 UI

- [ ] Supervisor JSONL 中的 `seq` 连续、`session_id` 单次稳定、动态任务 `agent_path` 可追溯。
- [ ] Host IPC 有同一序列上的 `control_requested/control_handled`，且绝不持久化 token/消息正文/Context。
- [ ] 严格游标 `/api/records` 在旧 Trace、缺号、会话轮换时返回 409，不把重放误当作继续执行。
- [ ] `agentos.capabilities` 不把 conditional/unsupported 视为支持；`--require-capability` 能在执行前拒绝。

- [ ] Ubuntu + openEuler 的 Harness CI 工作流完全成功。
- [ ] Host Demo 与动态声明 Demo 均成功，Report/Trace 可通过 JSON 解析。
- [ ] 失败注入可使关联子任务 `BLOCKED`，无关分支完成。
- [ ] SSE 首次有版本事件、文件变更后有增量事件，心跳不触发数据重新拉取。
- [ ] GPUI Native CI 通过 Rust 测试与 Linux 编译。
- [ ] 若声称支持真实 Wayland/Vulkan：附至少一次真实图形会话及显示器尺寸/缩放测试证据。
- [ ] 确认接口绑定 `127.0.0.1`，无外网端口、无未受控写路径。

## C. LayerFS / FC

- [ ] 区分 Fake SDK CI 与真实 SDK + Docker + daemon + FUSE 环境。
- [ ] 如果要宣称实机可用：至少完成成功 Commit、失败 discard、合并冲突、FC rewind/files 试验，保留 Commit/Branch 证据。
- [ ] FC 恢复只创建新 Branch，原 Branch 无变化。
- [ ] 不把 FC 文件回退包装为可撤销 HTTP/DB/邮件副作用。
- [ ] 不把逻辑 CPU/memory 预约描述为 LayerFS Docker 真正配额。

## D. 基准与实验

- [ ] 提供 Git SHA、内核/硬件、工具版本、Plan、采样次数与预热条件。
- [ ] 报告 p50/p95、样本数和异常值处理，未测项标记为“未测得”而不是 0。
- [ ] 合成 sleep 调度数据与真实模型 token/s、GPU KV、端到端 Agent 负载数据严格分离。
- [ ] 保存无秘密的测试证据，清理敏感 stdout/stderr、SQLite 和 Store。
- [ ] README、贡献指南、教程中的所有相对链接和 JSON 示例由文档 CI 检查。

所有清单项的“通过”均需可追溯至单次 CI/本机实验记录，不仅是文档中的目标状态。完整复现表见 [实验复现](reproducibility.md)。
