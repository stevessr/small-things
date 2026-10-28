# AgentOS native GPUI inspector (experimental)

This is the optional **Rust GPUI** desktop frontend. The fully functional
live DAG graph and timeline are provided by the dependency-free web UI;
GPUI now offers native task-list inspection, status counters, dependencies,
stdout/stderr and LayerFS FC metadata with **event-driven automatic refresh**.
The local server uses Linux inotify to push SSE change events; there is no
periodic state polling. Manual refresh remains available.
Both frontends use the same read-only local server. Native GPUI loads `/api/state?view=summary`, watches `/api/changes`, and lazily requests `/api/task/<id>` when a task is selected.

## Run on Wayland / openEuler

First start the local dashboard server (and pass real execution report and trace
paths), or use `python3 -m agentos.harness_run`; then launch the GPUI window:

```bash
cd small-things/agentos
python3 -m agentos.harness_ui --report /tmp/agentos.json --trace /tmp/agentos.jsonl
cd ui-gpui
cargo run --release --features desktop -- 8765
```

Uses published `gpui-pre = 0.3.10` + matching `gpui-pre-platform = 0.3.10`,
with Wayland and X11 enabled. Requires Rust stable, C/C++ toolchain,
Vulkan drivers and development headers, XKBCommon, X11 and Wayland libraries,
fontconfig and system render dependencies.

For a fast headless smoke test of the shared read-only protocol:

```bash
cargo test --no-default-features
```

The native task list requests **a 40-entry server-side page**, not an unbounded
task map. Every SSE notification or manual/page navigation loads only the
visible page, with stale responses discarded if the user has already switched
pages. Global task count and status totals are retained. The backend caches
the parsed snapshot until report/trace files change; multiple page requests
reuse it. The cache is in-memory, not a persistent task index. Full stdout/stderr
and resource metrics are fetched **only when an Agent is selected**; the local backend currently still parses the full report to produce each summary. The initial
window is clamped by GPUI to the current display's visible bounds; it does
not request a fixed resolution larger than the screen. SSE reconnects only
after disconnect, not at a periodic snapshot interval.

The native renderer is **not** required by the main Python/openEuler CI jobs; it has a dedicated GitHub Actions compile check.
Heavy GPU/platform builds are tested separately. On remote/headless hosts, use
the browser frontend; never expose the Harness UI HTTP server to untrusted
networks (it binds to localhost only).

The GPUI source is intentionally small: it has no command execution or file
writes, and no background filesystem scanning. A failed connection displays an
error and does not fabricate task state.

The Wayland/X11 window is non-resizable and opened with display-clamped bounds to
guarantee its initial dimensions and user-triggered size changes cannot exceed
the current display resolution. List and detail panes scroll independently.

## 验证和故障排查

```bash
# 无需图形会话，验证 Rust 模型与本机 SSE 传输
cargo test --no-default-features

# Linux Vulkan/Wayland 编译检查（无须运行窗口）
cargo check --features desktop

# 监控后端已启动时，可检查推送
curl -N http://127.0.0.1:8765/api/changes
```

GPUI 每次只构造至多 40 个任务视图，切换页/选中任务后按需请求详情；inotify/SSE 通知是事件来源，不使用固定频率的状态轮询。连接失败时在后台重连，但不伪造刷新结果。初始尺寸由 GPUI `Bounds::centered` 限制在当前显示器的可见区域内，当前禁用手动任意拉伸。

CI 已覆盖 Rust 逻辑和 Linux 原生编译，尚不覆盖真实 Wayland/X11 图形会话中的渲染、Vulkan 驱动兼容、中文字体与显示器动态切换。系统设计和 API 参见 [Harness UI 协议](../docs/harness-ui.md)。
