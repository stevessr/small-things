# 教程 01：从静态计划到 Agent 自主声明 DAG

## 1. 预检

```bash
cd small-things/agentos
python3 -m agentos.doctor --backend host --ui web
python3 -m agentos.plan_lint examples/agent-declarations.json --format json
```

预检结果应包含初始任务 `planner`。**动态子任务尚未被声明**，因此不会出现在静态拓扑序列中。此处没有运行 Agent。

## 2. 启动动态示例

```bash
python3 -m agentos.cli examples/agent-declarations.json \
  --report /tmp/agentos-declare.json \
  --trace /tmp/agentos-declare.jsonl
```

`planner` 是一个受 Supervisor 管理的进程；其 `agentos.demo_worker declare` 分支通过 `agentos.client.declare_tasks` 一次声明 `research_a`、`research_b`、`synthesis`。它们自动依赖 `planner`，而 `synthesis` 另外依赖两个 `research` 任务。最终共 **4 个任务**；不要求独立任务执行顺序固定。

## 3. 断言结果，而非只看 exit code

```bash
python3 - <<'PY'
import json
report = json.load(open("/tmp/agentos-declare.json", encoding="utf-8"))
expected = {"planner", "research_a", "research_b", "synthesis"}
assert set(report["tasks"]) == expected
assert all(result["status"] == "succeeded" for result in report["tasks"].values())
assert set(report["dag"]["synthesis"]["deps"]) == {
    "planner", "research_a", "research_b"
}
assert report["declared_by"]["synthesis"] == "planner"
print("DAG and declaration ownership verified")
PY
```

如果失败，应查看报告中失败任务的 `status/error/stderr`，以及 [Trace 事件规范](../trace-format.md)。子任务可以在同批中引用先于定义或后于定义的兄弟任务，但不允许悬空依赖或跨租户依赖。

## 4. 更改自己的计划

复制 `examples/agent-declarations.json` 并更改启动的 `argv`，或让自己的 Agent 使用：

```python
from agentos.client import declare_tasks

declare_tasks([
    {"id": "collect", "argv": ["python3", "collect.py"], "memory_mib": 128},
    {"id": "analyze", "deps": ["collect"],
     "argv": ["python3", "analyze.py"], "memory_mib": 128}
])
```

每次批量声明最多 **32 项**。所有动态子任务必须能通过 Parent 的权限与 DAG 校验。发生不合法声明时，整批拒绝，而不是先执行合法的一部分。参数和 IPC 返回格式见 [配置协议](../configuration.md)。

## 5. 清理

示例输出位于 `/tmp/agentos-declare.json`、`/tmp/agentos-declare.jsonl`。这些文件可能包含任务输出。仅在确认不用保存复现实验记录后，手动删除；不要将其提交到 Git。
