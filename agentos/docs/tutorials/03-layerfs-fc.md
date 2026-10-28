# 教程 03：LayerFS 分支与 FC 非破坏性恢复

此教程包含会影响 LayerFS Store/Branch 的操作，**不能在缺少真实 SDK、daemon、Docker/FUSE 环境时直接宣称通过**。初次使用前先完成 [LayerFS 官方 SDK 与本项目配置](../layerfs-fc.md)。

## 1. 仅校验计划（不会访问 LayerFS）

```bash
cd small-things/agentos
python3 -m agentos.plan_lint examples/layerfs-demo.json
python3 -m agentos.doctor --backend layerfs --ui web
```

`doctor` 只检测 Node、Docker CLI、环境变量和文件存在情况，不验证 Store 持久性或 Docker daemon 访问。

## 2. 先配置真实运行环境

在实际 Linux 机器上正确配置 `LAYERFS_PROJECT`、SDK 模块路径（如需要）、daemon、Store、Runtime Image 与 Docker Volume。环境变量的完整示例见 [LayerFS 指南](../layerfs-fc.md)。使用未初始化项目时，**只运行一次**：

```bash
python3 -m agentos.layerfs_init --source "$(cd .. && pwd)"
```

注意初始化可能包含隐藏或被忽略文件。确保源目录没有不应进入 LayerFS 的秘密。

## 3. 执行 DAG 并获取 Branch

```bash
python3 -m agentos.cli examples/layerfs-demo.json \
  --filesystem layerfs \
  --report /tmp/layerfs-report.json \
  --trace /tmp/layerfs-trace.jsonl
```

示例任务 `write` → `read` → `review`。成功后报告中 `tasks[write].filesystem_branch` 和 `filesystem_commit` 是后续查询 FC 的参数来源。失败任务可能没有 Commit。切勿凭文档猜测实际 Branch 名称。

## 4. 先查看历史，再选择恢复粒度

以下示例的 `BRANCH_FROM_REPORT`、`COMMIT_FROM_HISTORY` 必须替换为真实数据：

```bash
python3 -m agentos.layerfs_fc --mode history \
  --branch BRANCH_FROM_REPORT

python3 -m agentos.layerfs_fc --mode rewind \
  --branch BRANCH_FROM_REPORT --checkpoint COMMIT_FROM_HISTORY

python3 -m agentos.layerfs_fc --mode files \
  --branch BRANCH_FROM_REPORT --checkpoint COMMIT_FROM_HISTORY \
  --path /artifact.txt
```

`rewind` 与 `files` **均创建新 Branch**，不会覆盖来源 Branch。选文件恢复限定 1–64 个 UTF-8 普通文件，单文件不超过 4 MiB；不存在于指定 Commit 的文件可以从新分支中删除。完成后先审查新 Branch，测试成功再决定是否合并。

## 5. 验证重点

- 成功 Task 必须有可查询 Commit；失败 Task 的 Workspace 变更不得提交。
- 新 Branch 的恢复内容应与指定固定 Commit 相符；来源 Branch 不应被改变。
- 并行父任务修改同一文件时，冲突应显式失败，不应静默覆盖。
- 外部 HTTP、数据库、邮件操作无法用 FC 恢复；必须另行实施幂等与补偿事务。

目前 CI 只使用 **Fake LayerFS SDK**；真实 Docker/FUSE 验证步骤和证据模板见 [复现实验协议](../reproducibility.md)。
