# AgentOS Harness — 多 Agent 系统级执行时原型

> 竞赛原型（v0.3），目标平台为 **openEuler 24.03 LTS SP4**（同时在常见 Linux 上运行）。
> 本实现是使用 Linux OS 原语的 Agent supervisor，而不是定制内核或成熟的 AI Native OS。
> 代码位于 `small-things` 的独立 `harness` 分支，不修改既有工具。

## LayerFS 新后端与 FC 精细回退

新增 [LayerFS 1.1.0 + FC 使用指南](docs/layerfs-fc.md)：通过真实 LayerFS SDK 运行独立 Docker Workspace、提交分支，并可选择文件从固定 Commit 恢复到**新 Branch**。先执行 `python3 -m agentos.cli examples/layerfs-demo.json --filesystem layerfs`（需按指南配置真实 LayerFS）。本后端不等于完整宿主 cgroup 配额或跨 Docker Agent IPC。

## Harness UI · 可观测性控制台

完整浏览器版无需前端依赖，默认只监听本机 `127.0.0.1`，只读数据。
需要在 `agentos/` 目录运行：

```bash
# 终端 1：执行测试任务并记录结构化事件
python3 -m agentos.cli examples/agent-declarations.json \\
  --trace /tmp/agentos-live.jsonl --report /tmp/agentos-live.json

# 终端 2：实时查看运行过程（可以先于终端 1 启动）
python3 -m agentos.harness_ui \\
  --trace /tmp/agentos-live.jsonl --report /tmp/agentos-live.json \\
  --port 8765
# 浏览器打开 http://127.0.0.1:8765
```

浏览器版支持 DAG 自动布局、状态统计、任务搜索过滤、声明者与依赖、
FC 检查点、stdout/stderr、事件时间线和 1.2 秒自动刷新。
无远程命令执行、FC 回退按钮或任意路径读取 API。历史示例：
`python3 -m agentos.harness_ui --report examples/harness-ui-sample.json`。

新增 [原生 GPUI 查看器](ui-gpui/README.md)：直接消费同一 API，
提供任务列表、状态与 FC 查看，适合 Linux Wayland 桌面。
GPUI 原生前端需要额外 Vulkan/图形依赖，不属于 Python 核心的运行条件。

## 快速开始

需要 Linux 与 Python **3.11+**；核心部分仅依赖 Python 标准库。

```bash
git clone -b harness https://github.com/stevessr/small-things.git
cd small-things/agentos
python3 -m unittest discover -s tests -v
python3 -m agentos.cli examples/demo.json --trace /tmp/agentos.jsonl --report /tmp/agentos.json
python3 -m bench.benchmark --tasks 8 --parallel 4 --trials 3 --output /tmp/agentos-bench.json
```

CLI 返回 0 表示全部任务成功，1 表示至少一个任务失败或因依赖失败而阻塞，2 表示配置错误。

## 系统抽象

```text
AgentSpec (id, tenant, argv, deps, kind, cpu, memory, timeout, retry, priority)
         │
   dependency DAG / admission / resource reservations
         │
  Linux subprocess + RLIMIT_AS / RLIMIT_CPU + process group
         │                   ╲
 optional cgroup v2           local Unix socket broker
 memory.max / cpu.max         send, recv, context_get, context_put, spawn
 pids.max                     │
                             tenant-scoped compressed SQLite context store
         │
 lifecycle events → JSONL trace → result report / microbenchmark
```

任务状态：`PENDING → RUNNING → SUCCEEDED|FAILED`；
依赖失败可使尚未执行的任务变为 `BLOCKED`。每个 Agent 使用独立进程组；
失败进程不自动终止 DAG 中与其无依赖的其他 Agent。执行时的 `spawn`
会动态加入同一租户的子任务，且自动依赖其父任务，避免不确定的父子生命周期。

`kind` 的 `model/tool/process` 共用一份资源、调度与监控契约。
当前的 `model` 仅为进程适配入口：接入 vLLM、llama.cpp 或远程模型须提供实际适配器，
本版本**不虚构已经调用真实模型**。

## Agent 自主声明任务与依赖

新版支持 Agent 动态声明一组任务，并声明任务间的 DAG 依赖。由执行时
统一负责校验、资源准入、调度与失败传播。不是让 Agent 私自调用 shell
绕过调度器。每批最多 32 项；每个子任务**自动依赖声明者**，可额外依赖
同批兄弟任务或已有同租户任务，未知任务、环、重复 ID 和超预算整批拒绝。

宿主后端使用 Unix Socket：

```python
from agentos.client import declare_tasks
declare_tasks([
    {"id": "collect", "argv": ["python3", "collect.py"]},
    {"id": "analyze", "argv": ["python3", "analyze.py"], "deps": ["collect"]},
])
```

运行 `python3 -m agentos.cli examples/agent-declarations.json --report /tmp/dag.json`。
最终报告中的 `dag` 保存所有初始与动态任务的依赖、优先级、
逻辑资源预算，`declared_by` 记录声明来源，JSONL 事件记录每次纳管。

LayerFS 后端通过 `AGENTOS_DECLARATIONS` 环境变量提供任务唯一的
Workspace 文件路径。Agent 写入 `{"version":1,"tasks":[...]}`，
在成功提交 Workspace 后由 Runtime 读取并原子纳管。也可以使用
`agentos.declarations.write_manifest(tasks)`（需要容器能导入该 Python 模块）。
运行 `python3 -m agentos.cli examples/layerfs-declarations.json --filesystem layerfs`
需要先部署真实 LayerFS，CI 对应测试使用模拟 SDK。

## 使用 cgroup v2

未提供 `--cgroup-root` 时使用 `RLIMIT_AS`、`RLIMIT_CPU`、墙钟超时和进程组终止。
这是基本故障隔离，**不是强安全沙箱**。

在支持 systemd 的 openEuler/Linux 上，应由管理员为运行该程序的服务提供
**已委派且启用 cpu、memory、pids 控制器**的 cgroup v2 子树。
不要直接向整个机器的根 cgroup 写入限制。

```bash
# 示例：路径需要换成实际由 systemd Delegate=yes 委派的子树
python3 -m agentos.cli examples/demo.json \
  --cgroup-root /sys/fs/cgroup/.../delegated-agentos \
  --require-cgroup
```

运行时为每次执行创建独立子 cgroup，然后对每个 Agent 设置
`memory.max`、`cpu.max`、`pids.max`。如果内核或权限不满足，
`--require-cgroup` 会直接失败，而不会悄悄声称已启用内核配额。

**已知限制**：目前先创建子进程、再将 PID 加入 cgroup，存在非常短的
exec→attach 时间窗；因此强隔离和不可信多租户尚不成立。
应后续改为 clone3(CLONE_INTO_CGROUP)/pidfd 或受控原生 launcher，
并加入 user/mount/network namespace、seccomp 和 FD 权限约束。

## Agent 通信协议

子进程通过环境变量 `AGENTOS_BUS`、`AGENTOS_TOKEN` 访问本地 Unix Socket。
建议在受信 Agent 代码中导入 `agentos.client.request`：

```python
from agentos.client import request

request("context_put", key="shared-prompt", value="text context")
value = request("context_get", key="shared-prompt")["value"]
request("send", to="other_agent", payload={"status": "ready"})
messages = request("recv")["messages"]
request("spawn", task={"id": "new_agent", "argv": ["python3", "-c", "print('ok')"]})
```

IPC 对消息长度、队列深度做上限控制，并检查目标 Agent 的 tenant；
但令牌位于进程环境中，同 UID 的敌意进程不能视作强隔离。
不要在当前版本中执行不可信代码或在公共多租户机器上暴露敏感模型数据。

上下文缓存用于 UTF-8 prompt/消息文本，支持 zlib 压缩、SQLite 持久化和
tenant 维度隔离。它**不等于模型内部 KV Cache**，也不代表零拷贝 GPU 内存共享。
需要保持多次运行缓存时传入 `--context-db ./data/context.sqlite`；
默认 `:memory:` 仅在本次运行期间保留。

## 可验证性与评测

- `tests/test_runtime.py`：DAG、资源预约、运行时 spawn、IPC、跨租户访问、
  文本上下文复用、失败传播、重试、超时。
- `.github/workflows/agentos-harness.yml`：Ubuntu + openEuler 原生用户态测试，
  并在两种环境运行动态多 Agent Demo。
- `bench/benchmark.py`：同一监督器、同一进程睡眠工作负载，在
  1 个和 N 个并发资源槽位下比较总完成时间，提供所有样本、中位数和 p95。
  **这是调度并发性微基准**，不是 LLM token/s、真实硬件 KV 复用加速，
  也不是与 LangGraph/AutoGen/CrewAI 的公正性能对比。
- JSONL 包含纳管、启动、重试、完成、阻塞事件；启用 cgroup 时还能记录内核提供的\n内存峰值、CPU 使用量、OOM 事件和进程数指标（取决于控制器与内核暴露情况）。JSON 报告包含任务状态、
  各次尝试次数、耗时、隔离模式、压缩量、缓存命中等信息。

## 按赛题评分点划分的后续开发

| 评审项 | v0.1 覆盖 | 下一阶段关键工作 |
| --- | --- | --- |
| 系统机制创新 30% | 执行契约 / 资源预算 / 任务 DAG | Agent-as-process + 上下文亲和调度、临界路径 + 优先级衰减、可证明调度策略 |
| 功能深度 25% | 生命周期、动态任务、超时/重试、文本上下文、IPC | pidfd/clone3、隔离增强、checkpoint 恢复、真实模型与工具适配 |
| 性能效果 20% | 可复现实验脚手架 | 真实 LLM 负载、prefix/KV 共享接口、CPU/GPU/内存/通信性能对照 |
| 工程质量 15% | Python stdlib、模块化、CI | 原生 Rust/C supervisor、协议版本、配置校验和长期稳定性 |
| 实验分析 10% | 基础实验+结构化 Trace | openEuler 裸机测试、消融实验、故障注入、多轮多种规模统计 |

### 不应在答辩中声称已经实现的能力

真正跨 Agent 的 GPU KV Cache 共享或无损压缩、内核调度器修改、
多机通信、容器级安全边界、真实大型多 Agent 应用 benchmark、
长期在线可靠性。相关能力需要独立实现并提供实测数据。
