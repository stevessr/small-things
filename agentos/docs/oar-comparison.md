# 对照 botiverse/oar：从 Agent Supervisor 到可验证的 Harness 接口

参考项目：[botiverse/oar](https://github.com/botiverse/oar)，特别是 [foundations](https://github.com/botiverse/oar/blob/main/docs/design/foundations.md)、[record-stream](https://github.com/botiverse/oar/blob/main/docs/spec/record-stream.md)、[liveness](https://github.com/botiverse/oar/blob/main/docs/design/liveness.md) 与 [crash-resume](https://github.com/botiverse/oar/blob/main/docs/runtimes/crash-resume.md)。

**关系**：本项目的 `agentos/` 仍是 Linux/openEuler DAG Agent Supervisor；它不依赖 OAR 包，也没有复制 OAR 的 TypeScript 源码。OAR 是面向不同 coding-agent harness 的 provider-independent API；AgentOS 目前负责 CPU/内存预算、动态 DAG、Unix IPC、LayerFS Sandbox 和本机 GPUI。两个项目分层不同，因而先引入兼容的可观察性/能力契约，而不是直接将本地子进程解释为 Claude/Codex 会话。

## 借鉴点与实际实现

| OAR 的设计原则 | AgentOS 本轮实现 | 仍未支持 / 证据范围 |
| --- | --- | --- |
| 一个有序流，事件不可凭空合成 | `AgentRuntime._event` 为每条 Supervisor 事件赋予单调 `seq` 和执行 `session_id` | 没有模型 token、原生 tool-call frame 和真实 OAR request/response 流 |
| 精确 Agent 归属 | `agent_path` 是声明者链；`task` 是实际任务 ID；初始 Task 为 `[]` | 没有原生 coding-agent session graph；DAG deps 与 agent_path 是不同关系 |
| Replay 和 native Resume 是两回事 | 只读全量 JSONL 稀疏索引 `/api/records` 游标窗口；`/api/state` 仅投影真实可观察的 `session_id/last_seq`；缺失、截断、跨会话或旧格式返回 409 | 无法从 JSONL 恢复进程内存、模型会话和工具调用 |
| 能力不静默降级 | `agentos.capabilities` 返回 supported/conditional/unsupported 与证据；`require` 返回具名拒绝 | LayerFS 真正 Docker/FUSE 未在 CI 实机验证；声明不证明环境可用 |
| 数据与控制边界 | Host IPC 写入 `control_requested/control_handled`，有 request_id 关联；不记录 token/消息正文；GPUI/Web 依旧只读 | `handled` 只证明 Broker 处理，不证明客户端收到回复或目标 Agent 消费；未采用 OAR 的原生框架协议 |
| Liveness 不猜测 | 保留进程真实 `started/finished/blocked` 事实；没有事件不会凭心跳造出成功结果 | 不凭“长时间无消息”识别 hung 模型；暂无逐 Tool Span 心跳与 stalled reducer |

## 执行示例

```bash
cd small-things/agentos
python3 -m agentos.capabilities --backend host --format json
python3 -m agentos.plan_lint examples/agent-declarations.json

python3 -m agentos.harness_run examples/agent-declarations.json \
  --runs-root .agentos/runs --port 8765

# 另外一个 shell；从初始游标读取有序、已观察的 Supervisor 事实
curl -fsS 'http://127.0.0.1:8765/api/records?limit=100'
```

第一次响应包含 `session_id`、`next_seq`、`has_more`。继续查询时使用 `/api/records?after=上次next_seq&limit=100&session_id=上次session_id`；如果文件被轮转、截断或有缺失则返回 HTTP 409，不能把“有 409”自动解释为“没有更多事实”。

`seq` 是单次 AgentOS Runtime 中的序号，`time_ns` 是观测时间；跨进程实例不可将二者串成一条“全局事件序列”。任务 DAG 的依赖关系见 `dag[id].deps`，`agent_path` 只表示动态声明谱系，二者不能互换。

## 明确不做的伪兼容

1. **不会伪造 Claude/Codex/Pi 的 native sessionId、turnId、toolCallId**。AgentOS `session_id` 只是自己的调度执行 ID。
2. **不会把 LayerFS 文件树 fork/FC 当成 OAR 的模型会话 resume**。失去上下文或进程后需人工判断副作用。
3. **不会对旧 Trace 重新编号以制造“连续历史”**。旧文件依然可在状态 UI 中查看，但缺少游标证据时不支持严格重放。
4. **不会把有 Node/Docker 可执行文件或 cgroup 挂载等同于真正可用的沙箱**。`conditional` 表示仍需实机验证。
5. **不会将 `record_replay` 标为模型输出逐帧重放**。当前只有 Supervisor 事件，输出需要通过最终 Report 按任务查询。

## 后续工程阶段与验收门槛

| 阶段 | 目标 | 必须有的验证 |
| --- | --- | --- |
| A（当前） | 有序 Supervisor 事实、归属、严格游标与能力声明 | sequence/rotation/gap/legacy/HTTP/多级 Agent 单测及 Ubuntu/openEuler CI |
| B（已实现 Host 最小版） | IPC 请求和 Broker 处理结果以 request_id 关联 | 不泄露 Token/Env/消息正文；不把处理成功当作传输已送达；还缺原生 toApp 双向请求 |
| C | 根据每种原生 provider 协议实现可选 adapter，例如 ACP 或 OAR TS 独立进程桥接 | 真实 native 帧、生命周期、resume 能力由 SDK 证实；与 AgentOS DAG/task ID 分离 |
| D（部分完成） | 全量 JSONL 的临时稀疏索引已实现（不受 UI 尾窗限制），追加时增量索引；持久化 SQLite 索引尚未实现 | 12k 条记录、末尾半行、轮换、缺口与并发回放已测试；待完成持久化索引与规模基准 |

相关文档：[Trace 语义](trace-format.md)、[HTTP API](api-reference.md)、[能力矩阵](capabilities.md)、[运行会话与恢复边界](run-sessions.md)。
