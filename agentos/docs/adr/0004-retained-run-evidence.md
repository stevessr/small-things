# ADR-0004：保留每次独立运行证据并对其进行完整性检查

- 状态：已接受（原型）
- 背景：旧版 `harness_run` 复用固定报告/Trace 路径，重跑可能覆盖证据；HTTP 端口绑定失败前也可能修改历史文件。

## 决策

新增 `--runs-root`，在本地生成随机后缀的独立会话目录（0700），存放 Manifest、Report、Trace（0600）。绑定本机 HTTP 监听器成功后才开始初始化本次 Trace，并在任务结束后原子写入 Report、终局 Manifest 与 SHA-256。对已有默认路径保持兼容，不默认改变旧运行入口。

另提供只读 `agentos.sessions list/verify`：检索会话、核对 SHA-256/JSON 基本结构、区分执行结果与记录完整性。引入 [Session Manifest Schema](../session-manifest.schema.json) 约束字段。

## 取舍

- 新会话模式可以防止意外覆盖历史，但不自动压缩、轮转、清理。
- Manifest 的摘要与数据存放同一目录，不能防止恶意同时篡改，不具备数字签名的独立信任。
- 运行进程遭到 SIGKILL 或断电后，Manifest 可能停留 `running`；不自动推断失败或恢复中断的任务。
- 初始 Trace 原子写入，执行中仍逐条追加 JSONL；意外终止可能留下损坏的最后一行。

## 备选方案

直接使用数据库做事务事件日志（增加依赖与迁移复杂度）；把 Trace 轮转成日志服务（额外常驻服务）；继续默认覆盖历史（不利可复现）。当前选择单机、无第三方运行时依赖、手动保留/删除。

## 验证

[会话操作指南](../run-sessions.md)、[回归测试](../testing.md)、[安全边界](../security.md)。
