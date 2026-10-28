# ADR-0001：统一 DAG 控制面，执行后端分别实现

- 状态：已接受（原型）
- 背景：2026-10，Host Linux 进程管理和 LayerFS SDK 提供的 Docker Workspace 有不同资源与 IPC 语义。

## 决策

`AgentRuntime` 负责 `AgentSpec`、依赖、优先级、资源**预约**、失败传播与最终报告。`LayerFSRuntime` 复用该控制面，替换执行方法为 Node SDK 桥接，将每项任务置入自己的 LayerFS Branch/Workspace，并对成功任务 Commit。Host 模式仍使用 Linux 子进程、可选 cgroup 与 Unix Domain Socket。

## 理由

- 任务定义、验证与报告保持单一数据模型。
- 文件系统快照和 DAG 任务生命周期可对齐到 FC 检查点。
- 只需一份 DAG 失败传播测试，不重写两套调度器。

## 代价

- LayerFS 任务的 CPU/memory 字段**目前只进入逻辑预约**，未映射 Docker cgroup 配额。
- Host Broker 尚未投影到容器，因此 `send/recv/context` 不等价。
- LayerFS 真实 daemon/FUSE/Docker 仍需要实机测试；Fake SDK 只验证接口模型。

## 候选方案

完全共享 Host 文件目录 + subprocess（低成本但无独立文件历史）；完全改为容器调度器（与 Host IPC/cgroup 方案成本冲突）；统一 RPC Gateway（需额外协议与身份设计）。目前保留显式双后端，禁止静默 fallback。

## 验证

[配置和能力矩阵](../configuration.md)、[LayerFS/FC](../layerfs-fc.md)、[测试边界](../testing.md)。
