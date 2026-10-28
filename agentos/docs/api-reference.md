# Harness HTTP API 与数据契约

当前版本：Harness v0.4；`/api/state` 中的 `schema` 为整数 **1**。机器可读的接口规范：[OpenAPI 3.1](openapi.json)。

## 安全模型与端点

服务只监听 `127.0.0.1`，且要求 HTTP `Host` 精确等于 `127.0.0.1:<实际端口>`。**没有身份认证**；本机能够连接此端口的进程可能读取日志、任务输出和任务 ID。不可直接暴露到公网，也不要用反向代理绕开 Host 校验。

| Method | Path | Content-Type | 说明 |
| --- | --- | --- | --- |
| GET | `/` | text/html | Web UI |
| GET | `/app.js`, `/styles.css` | JS / CSS | 静态资源 |
| GET | `/healthz` | application/json | `{"ok":true}`；不证明真实 Worker/LayerFS 可运行 |
| GET | `/api/state` | application/json | 全量合并状态（含事件与已完成的任务输出） |
| GET | `/api/state?view=summary` | application/json | 摘要：`events=[]` 且仅选择有限任务字段 |
| GET | `/api/task/<id>` | application/json | 单个任务的完整结果和 DAG 元信息 |
| GET | `/api/changes` | text/event-stream | inotify 推送版本号；不是任务数据本身 |
| GET | `/api/records?after=-1&limit=100` | application/json | 有序事件重放；后续请求需带 `session_id`；无足够证据时 409 |

写操作统一拒绝：`POST` 为 405；未知路径返回 404；错误 Host 返回 403；Linux inotify 不可用时 `/api/changes` 返回 503。超过 **8 MiB** 的 Report 会导致状态接口返回 500；错误信息以 `{"error":"..."}` 返回。客户端不得从 500 响应推断 Worker 一定失败。

## 事实记录与严谨的游标

`GET /api/records` 返回 `schema/session_id/records/next_seq/has_more`，每个新事件包含连续的 `seq`、`session_id`、`agent_path`。仅证明此窗口内有序且连续，不表示可跨越被截断的历史前缀。超过内存读取上限或 Trace 被替换、旧格式无序号时返回 **409**，非法参数 **400**。没有写接口，也不提供原生会话继续执行；详见 [事件语义](trace-format.md)。

## 状态快照 `GET /api/state`

```bash
curl -fsS 'http://127.0.0.1:8765/api/state' | python3 -m json.tool
```

- `schema`：当前为 1，代表 **Harness UI 传输格式**，不等于 LayerFS SDK 版本。
- `session_id`、`last_seq`：来自真实 Trace/终局 Report；旧式无序号的文件显示为 `null`，不能将 `null` 当作新会话已结束。
- `tasks`：任务 ID → `AgentResult` 或 live Trace 派生的部分字段；任务运行过程中可能没有 `stdout` 和 `filesystem_commit`。
- `dag`：任务 ID → `{deps,kind,tenant,priority,cpu_units,memory_mib}`。来源：终局 Report（优先）或事件 `admitted/declared`。
- `declared_by`：动态子任务 ID → 声明者 ID。
- `events`：最近解析成功的结构化生命周期事件。**按文件末尾截断，不代表全量历史**。
- `counts`：键固定为 `pending/running/succeeded/failed/blocked`，根据当前状态计算。
- `total`：`tasks` 的数量。
- `isolation`、`budget`、`context`：主要来自终局 Report，运行中缺失时为占位值。
- `updated_utc`：服务生成当前快照的时间，**不是** Runtime 最后变更时间。

如果同时提供终局 Report 与 Trace，**Report 覆盖同名任务的 Trace 推导结果**；旧 Report 与新 Trace 混用会产生误导，务必配对使用。

### Summary 与按需详情

`GET /api/state?view=summary` 省略所有任务的 `stdout`、`stderr`、`resource_metrics`，`events=[]`。可选 `offset` 与 `limit` **必须同时出现**：`offset` 是按 ID 字典序排列后的 0 基索引（0–10000），`limit` 为 1–40；服务器只返回对应页的 `tasks/dag/declared_by`，但 `total` 和 `counts` 仍为全局结果。非法参数返回 400，报告损坏或超限仍返回 500。摘要中任务仅可能包含 `id`、`status`、`elapsed_s`、`attempts`、`exit_code`、`filesystem_branch`、`filesystem_commit`。

`GET /api/task/planner` 返回 `{"task":{...},"spec":{...}}`。任务 ID 满足 `[A-Za-z][A-Za-z0-9_.-]{0,63}`；非法或不存在时 404。选中任务后才读取详细 stdout/stderr 和资源指标：这是 **传输层 Lazy Load**，**不是**服务器端增量索引；服务器在缓存未命中或文件变化后仍要完整读取 Report 和 Trace；同版本的多个客户端和分页请求则复用进程内缓存，不能视为磁盘级的 O(1) 查询。

### 任务结果字段

| 字段 | 数据类型 | 定义 |
| --- | --- | --- |
| `id` | string | 任务 ID |
| `status` | string | `pending/running/succeeded/failed/blocked` |
| `attempts` | integer | 任务实际尝试次数 |
| `exit_code` | integer/null | 最后一次进程退出码；超时或未运行时可能为 null |
| `elapsed_s` | number | 执行耗时；未完成时可以缺省 |
| `stdout` / `stderr` | string | 进程最终结果文字，尚未完成时不保证存在 |
| `error` | string | 出错/阻断原因；成功时可为空 |
| `resource_metrics` | object | 运行时和内核暴露的指标，没有硬编码的固定全集 |
| `isolation` | string | Host/LayerFS 隔离说明 |
| `filesystem_branch` | string | 成功的 LayerFS Branch；Host 模式为空 |
| `filesystem_commit` | string/null | LayerFS Commit/FC 检查点；Host 或失败可能为空 |

## 实时事件 `GET /api/changes`

```bash
curl -N http://127.0.0.1:8765/api/changes
```

首次连接立即发送 `data: <version>`；文件发生 inotify 变化后发送新版本。`: heartbeat` 是约 20 秒的 SSE 注释，不应触发重取数据。当前没有 `id:` / `Last-Event-ID` 断点续传：**SSE 只是一条“状态已变更”通知**，订阅者收到消息后需要再次请求快照。GPUI 的重连间隔不是任务轮询间隔。

## 限流、大小与时间语义

- Report 最大读取 **8 MiB**，Trace 只看最后 **2 MiB**，最多 **4,000** 个有效事件。
- 浏览器图最多绘制 **160** 个节点；原生 GPUI 一页最多 **40** 项，详情才单独加载。
- 这些上限不是持久化历史保留策略；输出文件可继续增长。生产使用需补日志轮转与限制。
- 所有事件包含 Unix **纳秒**时间戳 `time_ns`，而 `elapsed_s` 单位是秒。两者不能混用。
- 实际任务完成后的指标由 Report 提供。界面当前**没有持续采样 CPU/RSS 曲线**。

## 兼容性与变更原则

v0.4 原型的 API 不保证公开稳定；消费者应按需读取已知字段，忽略额外字段，并容忍尚未完成任务的缺失字段。变更 `schema`、路由、HTTP 状态码或字段删除时，应同步修改 [OpenAPI](openapi.json)、[UI 规范](harness-ui.md)、[测试](testing.md) 与 GPUI Rust 反序列化层。关于状态机和事件详见 [Trace 格式](trace-format.md)。
