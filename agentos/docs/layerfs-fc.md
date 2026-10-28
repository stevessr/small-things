# LayerFS v1.1.0 + Function Calling Checkpoints (FC)

> 版本标注：AgentOS Harness v0.4，参考 LayerFS SDK v1.1.0。返回的 Commit/Branch 需在真实环境验证；当前 CI 使用模拟 SDK。

## 实现

使用 [Ephemeral-AI-Lab/layerfs](https://github.com/Ephemeral-AI-Lab/layerfs)
的公开 `@layerfs/agent` **v1.1.0** JS SDK。Node 桥接器
`agentos/layerfs_bridge.mjs` 每次只执行一项请求，不直接读取
LayerFS 的内部 SQLite Store。

- 任务开始：从 `main`、父 Agent 的已提交 Branch 或多个父分支合并结果
  派生独立 Branch，创建 LayerFS Sandbox 与 Workspace。
- 执行：在 LayerFS Docker Sandbox 内运行 argv；通过 GNU `timeout` 限制执行时间。
- 成功：提交 Workspace，生成可供后继 Agent 使用的 Branch + Commit ID；
  之后卸载并清理 Sandbox。
- 失败：不提交，丢弃 Workspace 变更；其它不依赖此任务的 Agent 照常执行。
- FC（Function Calling）：一个 DAG 工具任务对应一次 FC 检查点（提交消息 `FC: task_id`）。
  可查询调用历史，以固定 Commit ID 派生新 Branch、回退整个工具调用之后的文件树。
  也可从指定 Commit/Layer 读取被选文件内容，在**当前 Branch 的新 fork**
  上以单次原子 `fs.apply` 恢复；原 Branch 保持完整，其他文件不变。
- 冲突：交给 LayerFS 拒绝；不通过强制覆盖隐藏不同 Agent 的冲突。
- 超时或桥接器被中断：标记未知状态，不盲目重新执行有副作用的操作。

## 安装

按 [LayerFS 1.1.0 API 文档](https://github.com/Ephemeral-AI-Lab/layerfs/blob/v1.1.0/api/README.md)
在受支持 Linux 主机上构建其 Node 原生 binding、LayerFS daemon 和兼容的
Docker Sandbox 镜像；Store 必须位于本地 ext4/xfs/btrfs。
需要 Node 20+、Docker Engine、FUSE（若要投影可写 Workspace）以及项目镜像
包含 `sh`、GNU `timeout` 和要执行的工具。

启动示例（**先独立完成 LayerFS 的构建、环境配置和 Init**）：

```bash
# 以下均为示例：替换成已有的 LayerFS home / Store / native module / 镜像
export LAYERFS_HOME="$HOME/.layerfs"
export LAYERFS_STORE_PATH="/actual/volume/global/store.sqlite"
export LAYERFS_IMAGE="sha256:YOUR_REAL_IMAGE_DIGEST"
export LAYERFS_VOLUME="YOUR_EXISTING_LAYERFS_VOLUME"
export LAYERFS_DAEMON="/absolute/path/to/layerfs-daemon"
export LAYERFS_PROJECT="agentos-competition"
export LAYERFS_AGENT_MODULE="/absolute/path/to/layerfs/api/agent/sdk/src/index.js"

# 首次初始化项目树为 L0（包括 .git 与被忽略文件）；已有项目不要重复 Init
cd small-things/agentos
python3 -m agentos.layerfs_init --source "$(cd .. && pwd)"
python3 -m agentos.cli examples/layerfs-demo.json --filesystem layerfs \
  --report /tmp/agentos-layerfs.json --trace /tmp/agentos-layerfs.jsonl
```

`LAYERFS_AGENT_MODULE` 可不填，但必须使桥接器通过 Node 模块解析找到
`@layerfs/agent`。执行上下文来自已 Init 的 LayerFS 项目，不从本地
GitHub 分支偷偷复制文件。

## FC 调用级检查点与文件级恢复

```bash
# 查看一个 Agent Branch 上每次工具调用对应的 Commit
python3 -m agentos.layerfs_fc --mode history --branch ag-agent-abc123

# 从某次 Function Call 完成时的 Commit 创建新的回退分支
python3 -m agentos.layerfs_fc --mode rewind \
  --branch ag-agent-abc123 --checkpoint COMMIT_ID
```

FC 回退只管理 LayerFS 文件系统历史，**不能逆转外部 API 请求、数据库
提交、邮件发送或模型服务已执行的其他副作用**。需要上层补偿事务/
幂等键。当前工具调用的粒度为一个 DAG Task；单个 Task 中执行多个
shell 命令会共用同一个检查点。

### 按选定文件回退

检查点应填写 `fs.read` 可访问的**固定 Commit/Layer ID**，而非正在
变化的 Branch 名称：

```bash
python3 -m agentos.layerfs_fc --mode files \
  --branch ag-agent-abc123 \
  --checkpoint COMMIT_ID \
  --path /src/main.py \
  --path /config/app.toml
```

命令打印新的 `branch`，不修改传入的原 Branch；执行后可审查、
diff，再由上层决定是否合并/发布。选中的目标文件在检查点不存在时，
会在新 Branch 上删除当前文件。恢复范围为 **1–64 个 UTF-8 普通文件**，
目前每个文件上限 4 MiB；不恢复二进制文件、目录、权限、符号链接。
若文件读取被截断或类型不支持，整个 FC 操作拒绝提交。

## 竞赛与安全边界

- LayerFS 后端是外部 Docker 隔离，与 AgentOS 自己管理的宿主
  `RLIMIT/cgroup v2` **不是同一个机制**；当前任务的 CPU/memory 字段仅用于
  **调度资源预约**，尚未映射为 Docker/cgroup 真实配额。LayerFS CLI 中
  显式拒绝 `--require-cgroup` 与 `--cgroup-root`。
- 现有 `AGENTOS_BUS` Unix Socket 没有直接投影到 Docker 内；
  该后端支持 DAG、文件工件依赖与 Workspace 合并，但未接通
  `send/recv/context/spawn` 动态 IPC，不能宣称两种后端功能完全等价。
- LayerFS Store 当前为 Disposable profile，`synchronous=OFF`；
  最新提交可能在系统崩溃/断电时丢失，不要当作灾难恢复方案。
- LayerFS Sandbox 创建有开销；本版每次任务创建独立 Sandbox，
  未复用容器。网络与权限策略受 LayerFS/Docker 运行环境控制。
- 测试 `tests/fake_layerfs.mjs` 是**公开 SDK 接口测试替身**，
  不代表真实 LayerFS Docker/FUSE 与持久性验证。

## Agent 任务自主声明协议

LayerFS 执行器在 Agent 的 Docker Workspace 中设置：

- `AGENTOS_AGENT_ID`：当前任务 ID
- `AGENTOS_DECLARATIONS`：该任务专属的绝对文件路径
  `/workspaces/<ws>/.agentos/declarations/<task-id>.json`

Agent 成功执行时提交文件系统后，桥接器从其 Branch 读取任务唯一的
`/.agentos/declarations/<task-id>.json`，最多 **60 KiB**。格式：

```json
{
  "version": 1,
  "tasks": [
    {"id": "research", "argv": ["python3", "research.py"], "memory_mib": 128},
    {"id": "review", "deps": ["research"], "argv": ["python3", "review.py"],
     "priority": 5, "cpu_units": 1, "memory_mib": 128}
  ]
}
```

- 每批 1–32 个任务；先验证全部任务，再原子纳入待调度队列。
- `deps` 可引用本批或已有同租户任务，允许前向引用**本批**任务；
  不允许跨批悬空引用、循环依赖、跨租户依赖或重复 ID。
- 每个任务自动依赖声明它的 Agent，因此不会抢跑父任务的文件状态。
- 声明无效：声明者任务标记失败，不重试已成功执行的工具调用，
  也不发布该批任何子任务；不相关 DAG 分支继续执行。
- 在后继任务继承的 LayerFS Branch 中存在父级声明文件也不会重复触发：
  运行时只读取当前唯一任务 ID 的声明文件。
- 动态纳管只是**任务描述**，实际执行仍受预算、依赖和容错策略管理。

`examples/layerfs-declarations.json` 给出纯 shell 写 manifest 的例子。
本阶段没有将宿主 Unix Socket 直接投影到 Docker，也没有赋予
外部工具调用幂等或撤销保证。

## 下一步

实机 openEuler 连接 SDK + daemon + Docker，进行文件写入/故障回退/并行冲突
端到端评测；之后加入 FUSE 投影与 cgroup 配额统一控制、可跨 Docker 的 IPC
及更细的符号级回退（AST/函数范围恢复）。

## 恢复决策流程

1. **先查报告**：从 `report.tasks[task_id].filesystem_branch` / `filesystem_commit` 提取真实分支和提交标识。失败/未运行任务可能没有 Commit。
2. **查历史**：执行 `python3 -m agentos.layerfs_fc --mode history --branch BRANCH`，确认期望的不可变 Checkpoint。
3. **确定恢复粒度**：`rewind` 从 Commit fork 整棵树；`files` 只恢复指定 1–64 个 UTF-8 文件。两者均不会覆写原 Branch。
4. **核对结果**：比较新 Branch 的文件、依赖分支、编译结果后，再决定是否迁移工作流；不要把返回新 Branch 等同于已经发布。
5. **检查外部副作用**：HTTP 请求、邮件、远端数据库事务不在 LayerFS 文件历史中。必须独立处理业务补偿、幂等与撤销。

## 示例环境与验证级别

- 最小 Host 演示：`python3 -m agentos.plan_lint examples/layerfs-demo.json`（只校验图，不调用 SDK）。
- 模拟协议测试：`python3 -m unittest discover -s tests -p 'test_layerfs.py' -v`（无需真实 Docker/FUSE，但需要 Node.js）。
- 实机端到端：配置 `LAYERFS_PROJECT`、可解析的 `@layerfs/agent`、daemon、Store、Docker 镜像/Volume，运行成功/失败/合并/FC 文件回退，保留输出与可复现环境记录。
- 只有完成实机验证后，才能宣称真实 LayerFS 的 FUSE 投影、Merge 冲突与事务持久性已被验证。

参见 [任务清单格式](configuration.md)、[安全边界](security.md)、[测试与评估](testing.md)。
