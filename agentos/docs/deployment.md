# 部署与运行手册（Linux / openEuler / Wayland）

## 0. 前提与目录

主机推荐 openEuler 24.03 LTS SP4 或 Ubuntu Linux；Python 3.11+。默认 Host 后端不需要 Docker、不需要 Node、不需要图形系统。GPUI 是可选的 Linux 原生 UI；LayerFS 后端单独要求 Docker + Node + SDK + daemon。

```bash
git clone --branch harness https://github.com/stevessr/small-things.git
cd small-things/agentos
python3 -m agentos.doctor --backend host --ui web
python3 -m agentos.plan_lint examples/demo.json
python3 -m unittest discover -s tests -v
```

**Doctor 的“OK”仅是静态前置条件检测**：检测到 cgroup v2 挂载不代表已获系统委派，检测到 Docker CLI 不代表守护进程/镜像可用，检测到 Wayland 环境变量不保证 GPU 驱动、字体或 GPUI 本地窗口一定可启动。`doctor` 不安装任何依赖，不运行 Docker 或 Agent。

## 1. Host 后端：有数据、有 DAG、有 Trace

```bash
python3 -m agentos.cli examples/agent-declarations.json \
  --report /tmp/agentos-report.json \
  --trace /tmp/agentos-trace.jsonl
```

标准输出打印报告；`--report` 写入最终 JSON，`--trace` **追加** JSONL 事件。如果沿用旧 trace 文件会混入前次历史：请每次使用新路径，或先明确备份/归档并清理该文件。`harness_run` 会使用专属默认路径并覆盖上次运行的数据。

查看结果：

```bash
python3 -m json.tool /tmp/agentos-report.json
tail -n 20 /tmp/agentos-trace.jsonl
```

`agentos.cli` 退出码 **0** 全部成功、**1** 至少一个任务失败或阻断、**2** 配置或运行时错误。

## 2. 一键运行 + 本地 Web UI

```bash
python3 -m agentos.harness_run examples/agent-declarations.json \
  --report /tmp/demo-report.json \
  --trace /tmp/demo-trace.jsonl \
  --port 8765 --open-browser
```

UI 监听 **127.0.0.1:8765**，浏览器地址为 `http://127.0.0.1:8765`。进程默认在任务完成后继续提供只读 UI，按 Ctrl+C 结束；CI 使用 `--exit-after-run`。默认路径是 `.agentos/last-report.json` 和 `.agentos/last-trace.jsonl`，同一次进程开跑时覆盖，**不要用于永久保存历史**。

也可将运行和 UI 分开，在第二个终端：

```bash
python3 -m agentos.harness_ui \
  --report /tmp/agentos-report.json \
  --trace /tmp/agentos-trace.jsonl --port 8765
```

UI 仅显示记录的数据，不提供任意路径读写、启动任务或点击回退操作；因此可用于观测，但不能代替具备事务权限的独立运维命令。

## 2.1 保留每次独立运行的历史

```bash
python3 -m agentos.harness_run examples/agent-declarations.json \
  --runs-root .agentos/runs --port 8765 --exit-after-run
python3 -m agentos.sessions list --root .agentos/runs
```

历史会话由时间与随机后缀命名，目录权限为 0700，文件权限为 0600；运行结束后写入状态、退出码与报告/Trace SHA-256。可执行 `python3 -m agentos.sessions verify --session .agentos/runs/实际目录名` 检查完整性。见 [运行会话手册](run-sessions.md)。

## 3. Linux Wayland 原生 GPUI

```bash
python3 -m agentos.doctor --backend host --ui gpui
cd ui-gpui
cargo test --no-default-features
cargo run --release --features desktop -- 8765
```

先启动上面的 Harness UI 服务。GPUI 会监听同一个 SSE 端点；**只有收到文件变更事件才刷新摘要**，并在选中具体 Agent 时独立读取其 stdout/stderr/FC 元数据。每页最多 40 项、初始窗口不得超过当前显示器可见尺寸、暂不允许自由拖大尺寸。

Wayland 优先；如果使用 XWayland/X11，可由 GPUI 系统后端选择。未配置 `WAYLAND_DISPLAY` / `DISPLAY` 或 Vulkan 驱动的 SSH/headless 服务端，改用浏览器访问本地端口；不要将 HTTP 服务改成 `0.0.0.0`。

GPUI 使用 `gpui-pre = 0.3.10` 与同版本平台库；需 Rust 工具链、Vulkan 开发库、Wayland/X11/XKB/fontconfig 相关系统依赖。详见 [GPUI 文档](../ui-gpui/README.md)。

## 4. 可选宿主 cgroup v2

默认 `RLIMIT_AS` + `RLIMIT_CPU` + 墙钟超时 + 独立进程组，属于**尽力而为**的资源故障隔离。强制使用内核控制器时，管理员必须先通过 systemd `Delegate=yes` 委派 CPU、memory、pids 控制器的可写子树：

```bash
python3 -m agentos.cli examples/demo.json \
  --cgroup-root /sys/fs/cgroup/YOUR_DELEGATED_SUBTREE \
  --require-cgroup
```

`YOUR_DELEGATED_SUBTREE` 必须换成**实际已委派**的路径，不可填入宿主根 cgroup。当前 supervisor 先 `exec` 再把 PID 写入 cgroup.procs，存在一个非常短的限制生效前时间窗，不能视为安全隔离。相关威胁模型见 [安全边界](security.md)。

## 5. 可选 LayerFS Docker 后端

```bash
python3 -m agentos.doctor --backend layerfs --ui web
# 先按 LayerFS 官方构建 SDK/daemon、配置项目与 Docker volume
python3 -m agentos.layerfs_init --source "$(cd .. && pwd)"
python3 -m agentos.cli examples/layerfs-demo.json --filesystem layerfs
```

`layerfs_init` 是**首次初始化**，已初始化项目不要重复执行。真实 SDK/FUSE/Docker 的端到端测试**不是当前 CI 覆盖范围**；CI 使用 JS Fake SDK 作为协议替身。遇到失败按 [LayerFS + FC 文档](layerfs-fc.md) 定位。LayerFS 资源字段仅作调度器预约，不代表 Docker 真实 CPU/memory 限额。

## 6. 安装后部署

源码直接运行最简单；也可安装 Python 包并运行 `python3 -m agentos.harness_ui`。HTML/CSS/JS 打包在 `agentos/ui/` 包资源中，Node 桥接器在 `agentos/layerfs_bridge.mjs`。不要从不同分支拼接 UI 与 Runtime 的模块版本。

报告、Trace、SQLite、LayerFS Store 可能含 prompt、文件内容和其他敏感输出。放入权限受控目录，不要随意附加到公开 CI Artifact 或 Web 静态服务。
