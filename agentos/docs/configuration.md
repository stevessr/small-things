# 任务计划、动态 DAG 与协议参考

## 1. 非执行式预检

\`\`\`bash
cd small-things/agentos
python3 -m agentos.plan_lint examples/demo.json
python3 -m agentos.plan_lint examples/agent-declarations.json --format json
\`\`\`

预检只读取 JSON，验证配置、名称、图、租户与调度预约；不启动 Agent、不创建 LayerFS Sandbox、不打开 IPC Socket。成功返回 **0**，错误返回 **2**。\`--format json\` 输出 \`valid\`、\`tasks\`、\`budget\`、\`topological_order\`、\`edges\` 和 \`tenants\`。拓扑次序只是一个合法执行顺序，**不是**对调度器执行时序的保证。

## 2. Plan JSON

完整最小结构：

\`\`\`json
{
  "budget": {"cpu_units": 2, "memory_mib": 512, "max_tasks": 16},
  "tasks": [
    {"id": "collect", "kind": "tool", "argv": ["python3", "collect.py"], "memory_mib": 128},
    {"id": "summarize", "kind": "model", "deps": ["collect"],
     "argv": ["python3", "summarize.py"], "memory_mib": 128}
  ]
}
\`\`\`

Plan 顶层仅允许 \`tasks\`（必填，非空数组）和 \`budget\`（可省略）。计划预检拒绝多余字段；不能把报告 JSON 当执行计划。\`argv\` 为**参数数组**，不是单个 shell 命令字符串；确需 shell 时显式写 \`["sh", "-c", "command"]\`。

### 任务字段（以 \`AgentSpec\` 为准）

| 字段 | 类型 | 默认 | 约束 / 语义 |
| --- | --- | --- | --- |
| \`id\` | string | 必填 | \`[A-Za-z][A-Za-z0-9_.-]{0,63}\`；全图唯一 |
| \`argv\` | string[] | 必填 | 非空且每个参数非空，不含 NUL |
| \`deps\` | string[] | \`[]\` | 无重复、无自身 ID；只允许同租户、已存在或同批声明的任务 |
| \`tenant\` | string | \`default\` | 与 \`id\` 相同的名称规则；跨租户依赖拒绝 |
| \`kind\` | enum | \`process\` | \`process\` / \`model\` / \`tool\`，仅表示分类 |
| \`cpu_units\` | integer | \`1\` | 1–256；不得超过 budget CPU 维度 |
| \`memory_mib\` | integer | \`256\` | 32–1,048,576；不得超过 budget 内存维度 |
| \`timeout_s\` | number | \`30\` | 大于 0 且不大于 86,400 秒 |
| \`retries\` | integer | \`0\` | 0–5（失败后最多再执行几次；有副作用任务自行设计幂等性） |
| \`priority\` | integer | \`0\` | -100–100；高优先级优先考虑，同级按 ID 排序 |

\`budget\` 默认 \`{"cpu_units":2,"memory_mib":1024,"max_tasks":128}\`，三个字段必须为正整数；\`max_tasks\` 不得超过 10,000。预算是整个 Runtime 同时运行任务的 CPU/内存预约总和，**并不意味着**所有任务都会获得内核 cgroup 配额；后端区别见 [安全边界](security.md)。

## 3. DAG 准入与状态

图必须无环、无缺失依赖、无跨租户边。只有当全部依赖处于 \`SUCCEEDED\` 且 CPU/内存预约可用时，任务才可开始。失败后与其有关的下游任务递归变为 \`BLOCKED\`，无关任务继续执行。一个任务失败不会回滚外部服务的副作用。

\`\`\`mermaid
flowchart TB
  A[planner] --> B[collect_a]
  A --> C[collect_b]
  B --> D[merge]
  C --> D
  D --> E[report]
\`\`\`

## 4. Host Agent 自主声明任务

Host 子进程继承 \`AGENTOS_BUS\`、\`AGENTOS_TOKEN\`、\`AGENTOS_AGENT_ID\`、\`AGENTOS_TENANT\`、\`AGENTOS_KIND\`。在受信 Agent 中调用：

\`\`\`python
from agentos.client import declare_tasks

created = declare_tasks([
    {"id": "collect_a", "argv": ["python3", "a.py"], "memory_mib": 128},
    {"id": "collect_b", "argv": ["python3", "b.py"], "memory_mib": 128},
    {"id": "merge", "deps": ["collect_a", "collect_b"],
     "argv": ["python3", "merge.py"], "memory_mib": 128},
])
\`\`\`

- 每批声明 **1–32 个任务**，任务总数不能超过 \`max_tasks\`，依赖列表最多 128 个。
- 子任务**自动依赖声明它的父 Agent**；\`deps\` 可以引用同批前向定义的任务，或已经准入的同租户任务。
- 校验先于入队，未知任务、冲突、环、自引用、越权、预算过大均导致**整批拒绝**；无半批成功。
- 请求 \`spawn\` 仍可声明一个子任务，内部走相同的准入逻辑；不允许靠进程启动绕过调度。
- 父任务的普通进程副作用可能已经发生；子任务只有父任务 \`SUCCEEDED\` 后才真正执行。
- 对请求体有 **60 KiB** 上限，Broker 队列深度 128、一次 \`recv\` 最多 32 项。

## 5. Host IPC 请求（每连接单条 JSON）

以 Unix Socket 单行 JSON 发送 \`{"token":"...","op":"...","...":...}\`，结尾为换行。响应：

\`\`\`json
{"ok":true,"result":{"ids":["collect_a","collect_b"],"count":2}}
\`\`\`

失败为 \`{"ok":false,"error":"..."}\`；请优先使用 \`agentos.client.request\`，不要自己解析不可信消息。

| \`op\` | 关键字段 | 作用 |
| --- | --- | --- |
| \`send\` | \`to\`, \`payload\` | 向同租户 Agent 的有界队列发消息 |
| \`recv\` | 无 | 取出自己队列的最多 32 条消息 |
| \`context_put\` | \`key\`, \`value\` | 向租户隔离的 SQLite 文本缓存写入 |
| \`context_get\` | \`key\` | 查询本租户文本值 |
| \`spawn\` | \`task\` | 声明 1 个动态子任务，返回 \`id\` |
| \`declare_tasks\` | \`tasks\` | 原子声明 1–32 个任务，返回 \`ids\` / \`count\` |

Unix Socket 令牌通过环境变量传递；不构成针对同 UID 恶意进程的安全隔离。

## 6. LayerFS 声明协议

Docker 后端**没有**宿主 IPC Socket。Worker 写入 \`AGENTOS_DECLARATIONS\` 指向的自身 Workspace 中的 JSON 文件。Manifest 仅包含 \`version:1\` 与 \`tasks\`，上限 **60 KiB**，任务成功 Commit 后被读取和校验，失败拒绝整批纳管。用容器内可用的 Python 模块可调用 \`agentos.declarations.write_manifest(tasks)\`；无需 Python 时见 [LayerFS 示例](../examples/layerfs-declarations.json)。

LayerFS 子任务的文件基线来自父 Agent Commit，多个父分支由 LayerFS 合并；两种后端的“依赖准入”一致，但文件系统、IPC 和内核配额**不等价**。详见 [LayerFS + FC](layerfs-fc.md)。

## 7. 执行与报告

\`\`\`bash
python3 -m agentos.cli examples/demo.json \
  --report /tmp/agentos-report.json --trace /tmp/agentos-trace.jsonl

python3 -m agentos.harness_run examples/agent-declarations.json \
  --port 8765 --open-browser
\`\`\`

\`agentos.cli\` 退出码：0 全部成功、1 有失败/阻断、2 配置或运行时错误。Harness Runner 的退出码同理；默认在任务结束后保留本地 UI 服务，\`--exit-after-run\` 用于自动化测试。Host CLI 可选 \`--context-db\`、\`--cgroup-root\`、\`--require-cgroup\`；LayerFS 模式拒绝后两项和非默认的 \`--context-db\`，它们并非同一种隔离机制。

报告中的 \`tasks\` 是状态与输出，\`dag\` 是图结构和预算，\`declared_by\` 是动态创建关系，\`events\` 是生命周期事件。详细字段与 UI 请求见 [Harness UI 协议](harness-ui.md)。
