# AgentOS native GPUI inspector (experimental)

This is the optional **Rust GPUI** desktop frontend. The fully functional
live DAG graph and timeline are provided by the dependency-free web UI;
GPUI now offers native task-list inspection, status counters, dependencies,
stdout/stderr and LayerFS FC metadata with **event-driven automatic refresh**.
The local server uses Linux inotify to push SSE change events; there is no
periodic state polling. Manual refresh remains available.
The two frontends share exactly the same read-only `/api/state` JSON API.

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

The native task list renders at most **40 entries per page**; full stdout/stderr
and resource metrics are fetched **only when an Agent is selected**. The initial
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
