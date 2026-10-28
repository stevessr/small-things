# AgentOS native GPUI inspector (experimental)

This is the optional **Rust GPUI** desktop frontend. The fully functional
live DAG graph and timeline are provided by the dependency-free web UI;
GPUI currently offers a native task-list inspector, status counters, dependencies,
stdout/stderr, and LayerFS FC metadata, with an explicit **Refresh** control.
The two frontends share exactly the same read-only `/api/state` JSON API.

## Run on Wayland / openEuler

First start the local dashboard server (and pass real execution report and trace
paths); then launch the GPUI window:

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

The native renderer is **not** required by the main Python/openEuler CI jobs; it has a dedicated GitHub Actions compile check.
Heavy GPU/platform builds are tested separately. On remote/headless hosts, use
the browser frontend; never expose the Harness UI HTTP server to untrusted
networks (it binds to localhost only).

The GPUI source is intentionally small: it has no command execution or file
writes, and no background filesystem scanning. A failed connection displays an
error and does not fabricate task state.
