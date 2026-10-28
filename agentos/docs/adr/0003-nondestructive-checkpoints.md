# ADR-0003：FC 回退始终创建新 LayerFS Branch

- 状态：已接受（原型）
- 背景：多个 Agent 的文件输出可能合并，直接移动或改写原 Branch HEAD 会丢失工作证据，也可能影响并发任务。

## 决策

一次成功 DAG Task 对应一次 `FC: <task-id>` 的 Commit 记录。`history` 查询历史；`rewind` 从固定 Commit 新建 Branch；`files` 在当前 Branch 的新 fork 中，从固定 Commit 按选定路径恢复 UTF-8 文件。**不修改来源 Branch**。

## 理由

- 回退产物有独立标识，可在合并前检查差异并执行测试。
- 文件级回退与其他文件的改动解耦（只针对所选普通文本）。
- 出错时保留原有分支证据，便于审查。

## 代价和边界

- 当前回退仅适用于最多 64 个 UTF-8 普通文件，每文件 ≤4 MiB；无目录/二进制/symlink/权限恢复。
- **不回滚**外部 API、数据库事务或邮件；需要单独的幂等/补偿机制。
- Docker/FUSE/真实 LayerFS 的冲突与持久性行为尚需实机测试；CI Fake SDK 不提供这类证据。
- 旧 Commit 所在项目和生命周期由 LayerFS 管理，不能将 FC 当作离线备份。

## 替代方案

直接改写当前 Branch HEAD（具有破坏性，拒绝）；直接用 Git revert（不能覆盖未纳入 Git 的全部工作区文件）；工具操作全事务（跨外部 API 不现实）。当前明确采用非破坏性 fork。

## 验证

[FC 使用指南](../layerfs-fc.md)、[安全边界](../security.md)、[能力成熟度](../capabilities.md)。
