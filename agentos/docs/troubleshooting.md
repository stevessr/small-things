# 故障排查：症状 → 证据 → 修复

以下命令均从 \`small-things/agentos/\` 执行，除非明确切换目录。先用**不执行任务**的两个命令收集证据：

\`\`\`bash
python3 -m agentos.doctor --backend host --ui web --format json
python3 -m agentos.plan_lint examples/demo.json --format json
\`\`\`

## 常见报错与处理

| 现象 / 文本 | 诊断 | 操作 |
| --- | --- | --- |
| \`PLAN INVALID: unknown dependency\` | 静态依赖 ID 不在同一 Plan | 检查大小写、任务 ID；动态声明只能引用已有任务或同批任务 |
| \`dependency cycle detected\` | A→B→A 等环 | 修改 \`deps\`，别依赖运行时重试解环 |
| \`cross-tenant dependency denied\` | 两个任务的 \`tenant\` 不同 | 将同一工作流纳入合法同租户计划；不要绕开 Broker |
| \`task ... exceeds cluster budget\` | 单任务预算大于全局预算 | 提高整体预算或降低任务资源需求；以实际主机能力为准 |
| \`no schedulable tasks\` | 依赖/预约与运行状态出现不一致 | 保存 Report、Trace，先执行 \`plan_lint\`，检查动态声明和失败传播 |
| \`AGENTOS_BUS\` / \`AGENTOS_TOKEN\` 缺失 | 在普通 shell 中调用了 Host IPC 客户端 | 必须由 Host supervisor 启动并注入这两个环境变量 |
| \`target inbox is full\` | Broker 队列 128 项已满 | 减少发送速率，接收方及时 \`recv\` |
| \`cgroup enforcement requested\` / 权限错误 | 没有有效委派路径或控制器 | 使用已委派的 cgroup v2 子树；测试可先移除 \`--require-cgroup\` |
| \`LayerFS bridge timeout\` | Docker/daemon/SDK 通信被中断 | **先检查 sandbox/commit 状态**，不要直接重试副作用任务 |
| \`LAYERFS_PROJECT must name\` | 环境变量未配置 | 在运行进程环境中设置已初始化的项目名 |
| \`Node.js >=20\` | Node 版本太低或未安装 | 检查 \`node --version\`，使用 Node 20+ |
| FC \`Unknown branch / checkpoint\` | Branch 与不可变 Commit ID 对不上 | 先执行 \`--mode history\`，确认 ID 和 LayerFS Project |
| FC 文件回退失败 | 非文本/目录/符号链接/单文件过大/读取截断 | 仅选择 UTF-8 普通文件，每个 ≤4 MiB，最多 64 个 |
| Web UI 空白/停止更新 | UI 没有 Trace/报告，或 inotify 监听不可用 | \`curl /healthz\`、\`curl -N /api/changes\`，确认文件确实在写 |
| \`403 Invalid Host\` | 通过 hostname / 远程代理访问 | 使用 \`http://127.0.0.1:<port>\`；不要放宽 Host 校验 |
| \`503 Native Linux file event monitoring unavailable\` | 非 Linux、路径父目录不存在或 inotify 监听失败 | 创建输出父目录后重启 UI；必要时手动刷新 |
| \`/api/task/<id>\` 返回 404 | 选中任务尚未准入或 ID 不合法 | 查询 \`/api/state?view=summary\` 的任务 ID |
| GPUI 黑屏/无窗口 | Wayland/X11/Vulkan/驱动/字体问题 | \`doctor --ui gpui\`，核查 \`WAYLAND_DISPLAY\` 与 GPUI CI |
| GPUI 内容未刷新 | SSE 连接断开或监控文件不匹配 | 检查 \`/api/changes\`，可手动点击“刷新快照” |

## 事件流诊断

\`\`\`bash
curl -sS http://127.0.0.1:8765/healthz
curl -N http://127.0.0.1:8765/api/changes
curl -sS 'http://127.0.0.1:8765/api/state?view=summary' | python3 -m json.tool
\`\`\`

首次建立 SSE 连接应收到 \`data: 0\` 或更新后的版本号；追加 Trace 或原子替换 Report 后，版本号应递增。约 20 秒发的 \`: heartbeat\` 是 **SSE 注释**，不会触发重新获取任务数据。GPUI 在断线后尝试重连，不使用定时任务轮询。

报告/Trace 从最近的指定路径读；文件内容可包含敏感 prompt、报错和业务数据。分享日志前请删去令牌与秘密。任务执行失败后仍可能已产生外部 API 副作用，不能只通过文件检查点证明已恢复。

## 快速区分宿主与 LayerFS

\`\`\`bash
python3 -m agentos.doctor --backend host --ui web
python3 -m agentos.doctor --backend layerfs --ui gpui
\`\`\`

LayerFS 不支持 Host \`--context-db\` 与 \`--cgroup-root\`。在真实 SDK + Docker 未配置前，首先使用 \`examples/demo.json\` 验证 Host Runtime，再切换 \`examples/layerfs-demo.json\`；不要把 Host IPC 的 \`agentos.client.request\` 放到还未投影 Unix Socket 的 Docker Sandbox 内。
