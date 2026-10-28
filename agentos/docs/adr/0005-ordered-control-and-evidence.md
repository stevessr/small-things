# ADR-0005：记录与控制统一排序，重放只认实际证据

- 状态：已接受（AgentOS Supervisor 事实范围）
- 参考：[OAR record-stream](https://github.com/botiverse/oar/blob/main/docs/spec/record-stream.md)、[OAR foundations](https://github.com/botiverse/oar/blob/main/docs/design/foundations.md)

## 背景

没有稳定序号的 JSONL 只适合单次演示。若控制请求与运行事件各走独立、无关联的日志，恢复、审计、竞赛评测无法回答“某个 declare_tasks 是否在任务启动前被接受”。另外，Trace 尾部裁剪与跨进程轮换使得“所有历史都在”并不成立。

## 决策

1. 单个 `AgentRuntime` 分配随机 32 位十六进制 `session_id`，每个 Supervisor 观察事实单调递增 `seq`，`agent_path` 为声明者祖先链、`task` 为实际任务 ID。首次事件 seq=0。此 ID **不是** OAR 的 native coding-agent session ID。
2. Host Broker 的**已认证**操作生成 `control_requested` 和 `control_handled`，由 `request_id` 关联。只记操作类别、处理标志和错误类别；**不记录**鉴权 token、请求 payload、Context 文本。
3. `control_handled(accepted=true)` 只说明 Broker 已计算结果并准备写回，不说明客户端已收到、目标 Agent 已消费消息或外部副作用已提交。这些需要独立的后续事实证明。
4. 只读 `/api/records` 按 `session_id`、`after`、`limit` 返回有序连续的已观测事件。如果检测到旧日志、缺号、截断前缀、运行身份替换，显式报 409。缺失记录不重建、不猜测。
5. `harness_run --runs-root` 的 Manifest 和终局 Report 记录 Supervisor session ID、最后 seq；`agentos.sessions verify` 同时检查摘要与序列一致性。

## 不变量

- `time_ns` 是时间测量，不是全序依据；不同会话的 `seq` 不能直接比较。
- `agent_path` 是动态声明的谱系，DAG 的 `deps` 才是执行依赖，不能互相替代。
- `/api/changes` SSE 只是“状态变化通知”，`/api/records` 才是本地有限证据重放。
- `replay` 不等于 resume，文件系统 FC 不等于恢复进程或模型内存。
- 本阶段仍未保存任意 provider 的原生帧和原生会话控制记录；不宣称兼容 OAR API。
- Host IPC 的错误可被记录为 `control_handled`；没有响应时绝不补写成功记录。

## 代价与下一阶段

当前 `/api/records` 以每 128 条记录一个偏移建立**内存稀疏索引**，首次扫描整份 JSONL，后续只读取追加事件；`/api/state` 仍限于 2 MiB/4000 条的轻量视图。没有磁盘持久化 SQLite 索引、持久化 native frame、跨进程续执行或双向 provider 控制。原始 Trace 一旦缺失或被改写，即使有索引也不提供伪重放。后续可增加应用层的持久日志与索引，且必须保留历史来源、缺口和 native resume 与 replay 的区别。

## 证据

[OAR 比较](../oar-comparison.md)、[生命周期 Trace 契约](../trace-format.md)、[HTTP API](../api-reference.md)、[能力声明](../capabilities.md)、[测试矩阵](../testing.md)。
