# ADR-0002：事件通知与只读快照分离

- 状态：已接受（原型）
- 背景：任务事件产生时间不均匀；GPUI 要求 Lazy Load、收到更新才刷新，且窗口不大于显示器。

## 决策

Runtime 追加 JSONL，完成后生成终局 Report；本机只读 HTTP 根据两者构造状态。Linux inotify 监听**指定的文件路径**，`/api/changes` SSE 只发送变更版本号。客户端接到事件后请求 Snapshot；GPUI 先拿 `view=summary`，选中任务后才请求 `/api/task/<id>`。不提供固定周期的状态查询。

## 理由

- 没有事件时不重复读取大型 JSON。
- Web 和 GPUI 共用 API，不重复解析 Runtime 内部状态。
- 无需额外数据库服务，原型可在普通 Linux 用户态运行。

## 代价

- SSE **不是**持久事件日志，也没有 `Last-Event-ID` 续传；断线后需要重取状态。
- Summary 是**传输层**裁剪，当前服务端仍读取 Report/Trace。
- Linux inotify 可用性与被监控文件父目录有关；心跳只维持连接，不触发状态重新计算。
- 大型 DAG 对浏览器绘制节点有限制，GPUI 采用 40 项分页。

## 备选方案

固定 1s/5s 轮询（简单但浪费并可能漏掉短暂状态）；WebSocket 双向 RPC（操作权限面更大）；常驻数据库 + 消息总线（较重）。当前选择 SSE + 快照、没有写端点。

## 验证

[HTTP 契约](../api-reference.md)、[SSE/GPUI](../harness-ui.md)、[CI 覆盖](../testing.md)。
