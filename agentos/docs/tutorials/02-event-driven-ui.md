# 教程 02：Harness UI 的 inotify → SSE → Lazy Load

## 1. 启动监控和任务

```bash
cd small-things/agentos
python3 -m agentos.harness_run examples/agent-declarations.json \
  --port 8765 --report /tmp/agentos-ui-report.json \
  --trace /tmp/agentos-ui-trace.jsonl
```

打开 `http://127.0.0.1:8765`。所有 HTTP API 都只在 **127.0.0.1** 本地可用；此服务只读。该命令会启动真实 Demo 子进程，完成后服务会继续保持直到 Ctrl+C。

## 2. 检查 REST 端点

在另一个终端：

```bash
curl -fsS http://127.0.0.1:8765/healthz
curl -fsS 'http://127.0.0.1:8765/api/state?view=summary' | python3 -m json.tool
curl -fsS http://127.0.0.1:8765/api/task/planner | python3 -m json.tool
```

摘要不会返回每个任务的长 stdout/stderr/resource_metrics；选择具体 ID 才取详情。详细状态及单位见 [API 参考](../api-reference.md)。`/healthz` 只是 HTTP 存活测试，不代表 Agent 或 LayerFS 正常运行。

## 3. 验证事件源

```bash
curl -N http://127.0.0.1:8765/api/changes
```

首次连接应立即收到 `data: N`，N 是当前变更版本。之后在被监控的 Trace/Report 发生变化时，inotify 使服务发送新的 `data: N+1`。没有数据变化时，仅出现 `: heartbeat` 注释，**不应触发一次状态刷新**。

若运行已完成而看不到新事件，这是正常现象。要在隔离测试中验证一条新事件，可以另起一次运行，并指定新的 Trace/Report 路径；也可以使用现有 `tests/test_harness_ui.py`，它已经验证追加、原子重命名与 SSE 推送，不必污染用户数据。

## 4. 可选原生 GPUI

先安装 Rust + Vulkan + Wayland/X11 依赖，参照 [GPUI 安装指南](../../ui-gpui/README.md)：

```bash
cd ui-gpui
cargo run --release --features desktop -- 8765
```

GPUI 当前每页最多创建 40 个任务组件，选中任务才请求详情；监听 SSE，而不是每秒轮询。窗体初始请求 1140×760 **逻辑像素**，由 GPUI 限制在实际屏幕可见区域内，当前设置为不可手动无限放大。真实 Wayland/Vulkan 显示兼容性仍需要本机实测。

## 5. 故障定位

- `403`：请求的 Host 不是 `127.0.0.1:<端口>`，不要关闭检查。
- `404 /api/task/...`：该任务尚不存在或 ID 不合法。
- `503 /api/changes`：Linux inotify 无法监听；Web UI 仍保留手动刷新。
- `500 /api/state`：Report 不可读或超过 8 MiB，不能推断 Agent 一定失败。
- SSE 断线只触发重新连接，不可将重连当成状态定时轮询。

见 [完整排障手册](../troubleshooting.md)。
