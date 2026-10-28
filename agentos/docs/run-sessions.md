# 运行会话、历史保留与完整性验证

从 `harness` 的 v0.4 开始，可以使用 `--runs-root` 保存每次独立执行结果，而不再只保留 `.agentos/last-report.json`。

Manifest 的机器可读约束见 [JSON Schema](session-manifest.schema.json)，设计决策见 [ADR-0004](adr/0004-retained-run-evidence.md)。

## 1. 独立会话运行

在 `small-things/agentos/` 目录：

```bash
python3 -m agentos.plan_lint examples/agent-declarations.json
python3 -m agentos.harness_run examples/agent-declarations.json \
  --runs-root .agentos/runs --port 8765 --exit-after-run
```

每次自动创建 `YYYYMMDDTHHMMSSZ-<随机后缀>` 新目录。**不会覆盖**已有会话。运行中的 Web/GPUI 仍通过同一个本机 `127.0.0.1` SSE 服务消费实时 Trace/Report；执行完成后，如果使用 `--exit-after-run`，服务自行退出。

| 文件 | 含义 | 写入方式 |
| --- | --- | --- |
| `manifest.json` | run_id、独立的 supervisor session_id、最后 seq、开始/结束时间、计划 SHA-256、结果码及文件摘要 | 临时文件 + 原子替换 |
| `report.json` | 终局 DAG/任务状态、错误、stdout/stderr、FC Commit 等 | 临时文件 + 原子替换 |
| `trace.jsonl` | 执行事件，每行 JSON 对象 | 初始事件原子写入，运行中追加 |

会话目录为 **0700**，上述文件新建为 **0600**。不要把此模式理解为跨用户强安全隔离；同 UID 的程序仍可能读取本地进程及文件信息。

默认模式保持兼容：不传 `--runs-root` 时仍使用 `.agentos/last-report.json`、`.agentos/last-trace.jsonl`，会覆盖上次记录。为避免语义冲突，**`--runs-root` 不能与 `--report` 或 `--trace` 同时传入**。

## 2. 检查历史及完整性

```bash
python3 -m agentos.sessions list --root .agentos/runs
python3 -m agentos.sessions list --root .agentos/runs --format json

python3 -m agentos.sessions verify \
  --session .agentos/runs/替换为实际目录名 --format json
```

`verify` 对比 `report.json` 和 `trace.jsonl` 的 SHA-256，并检查 JSON/JSONL 基本结构。退出码：**0** 完整、**2** 缺失/损坏/未结束的记录。一个退出码为 1 的 Agent 运行仍可能有**完整且校验通过**的记录；`status=failed` 与 `integrity=invalid` 是完全不同的概念。

`manifest.status` 取值 `running/succeeded/failed/error/interrupted`：运行中尚无终局报告或摘要，因此 `integrity=incomplete` 是正常值；异常崩溃后可能保留 `running`，不会自动推定任务已恢复或已回滚。**不支持从该目录继续调度未完成任务**。

新增 `session_id` 与 `last_seq` 用于重放 Trace 的游标完整性验证；`session_id` 与运行目录名 `run_id` 是两种不同身份，并非 Claude/Codex 等原生模型会话 ID。记录文件中途缺失、序列断裂应报错而非自动续跑。

SHA-256 是**偶发损坏检测**，不是数字签名或不可抵赖审计：能够修改报告的攻击者也能重新计算摘要并修改 manifest。若要长期保留可信证据，应将文件封存到独立备份/签名系统。

## 3. 重新打开某次历史记录

不会重新执行任何 Agent：

```bash
python3 -m agentos.harness_ui \
  --report .agentos/runs/实际运行目录/report.json \
  --trace .agentos/runs/实际运行目录/trace.jsonl --port 8765
```

如果需要原生桌面查看器，在另一个终端运行：

```bash
cd ui-gpui
cargo run --release --features desktop -- 8765
```

GPUI 仍使用 SSE 事件驱动更新与 40 个任务分页；历史记录静态不再变化时，启动后的首条 SSE 消息即可触发首次加载。监控 API 只读，不提供浏览器端删除或恢复按钮。

## 4. 恢复和保留策略

- 当前只做**会话文件保留**，不执行自动清理、文件轮转、后台压缩或数据库重放。
- 写终局报告采用原子替换，降低部分文件截断概率；运行中逐条追加的 Trace 仍可能在断电时留有部分行，UI 尾读会忽略无效行，但 `verify` 会拒绝损坏的 JSONL。
- 会话包含 stdout/stderr、业务输入和可能的秘密；不应直接提交 Git 仓库或公开 Actions Artifact。删除历史目录需操作员单独确认。
- 失败/超时的任务可能已经产生外部 API/数据库副作用；保留记录不是 FC 回退，也不代表恢复成功。

关联：[实验复现模板](reproducibility.md)、[安全边界](security.md)、[HTTP API](api-reference.md)、[运行与部署](deployment.md)。
