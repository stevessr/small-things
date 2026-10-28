# 安全边界与威胁模型

**使用定位：受信开发机/竞赛实验证明原型。** 本项目未达到不可信多租户或生产执行沙箱的安全要求；下述边界针对实际实现，避免把控制面限制描述成内核强制隔离。

## 身份与权限

- Host Agent 的通信使用 Unix-domain socket + 64 字节十六进制随机令牌；Socket 目录权限限制为 0700，Socket 权限为 0600。
- Broker 检查令牌、目标 Agent 和 tenant，对单条请求限制 60 KiB、目标队列 128 条；但 **同一 Unix UID** 下恶意进程可能读取环境变量、进程内存或文件系统，不能仅靠这些机制隔离彼此。
- `tenant` 是控制面逻辑命名空间，不等于 Linux 用户/namespace 的强安全边界。需要可信 Agent，可在同一操作系统账号中执行。
- 任务清单中的 `argv` 最终启动子进程；**不要执行不可信 Manifest、外部用户输入构造的脚本**。Host `sh -c` 任务没有自动 shell 注入防护。

## 进程与资源

- Host 模式默认 `RLIMIT_AS`、`RLIMIT_CPU`、wall timeout、独立进程组。进程组清理并不能防止全部跨进程泄漏、恶意 fork 或继承的特殊 FD。
- cgroup v2 需要管理员**实际委派** cpu/memory/pids 控制器；在 `exec` 后 attach PID 仍有时间窗。尚无 clone3 `CLONE_INTO_CGROUP`、pidfd、seccomp、user/mount/net namespace、最小特权 FD 策略。
- LayerFS Docker 的资源配额由 SDK/容器环境决定，AgentOS 的逻辑预算不映射到容器 cgroup。Docker 有额外依赖与访问权限风险。
- 当前没有真正的 GPU KV Cache 隔离或共享、GPU 限额、集群分布式调度。

## 文件系统与 FC

- 每成功的 LayerFS DAG Task 为一次 FC Commit，`history` 查询，`rewind` / `files` 在**新分支**恢复；原分支不会被覆盖。
- `files` 限定 1–64 个 UTF-8 普通文件、单文件约 4 MiB；不处理二进制、目录、权限或 symlink。对于超限/读取截断，必须拒绝整个回退请求。
- FC 恢复**不**回滚已发出的外部 HTTP 请求、邮件、数据库写入、远程模型调用；需要业务幂等键、补偿事务和人工审核。
- LayerFS Store/daemon 的文件生命周期、崩溃持久性依赖外部组件；当前未证明断电恢复。不要把一次 Commit 当作可离线备份。

## 控制审计和游标可用性

Host Broker 仅对**通过 capability token 认证的控制请求**写入 `control_requested/control_handled`；记录不携带 token、消息正文、Context 值，也不记录原始任意操作名。认证失败不会暴露匿名客户端的任意 payload，但这不是针对恶意同 UID 进程的强隔离。处理状态不等于最终投递/消费结果。

`/api/records` 只对已观察到的 Supervisor 事件进行窗口重放，`session_id` 和 `seq` 用于防止误拼接跨运行历史。旧版文件无序号、前缀截断、身份变化或缺号时返回 409。**这是数据完整性/可用性边界，不是鉴权**。拥有本机 UI 端口访问权的进程可读取此端点的任务与控制事件；不要通过外部反向代理转发它。

## Web/GPUI 监控

- HTTP 仅绑定 **127.0.0.1**，`Host` 精确校验避免 DNS rebinding；没有跨域授权，不提供任何写操作。
- `/api/state`、`/api/task/<id>` 能返回 stdout/stderr、内部 DAG、FC ID 等；**本机可访问该端口的进程**有机会读取这些数据。不要将本机端口或其代理直接暴露到公网。
- SSE 是只读推送，inotify 仅监控明确指定的 Report/Trace 文件，不允许 HTTP 客户端选择任意路径。GPUI 的懒加载仅减少客户端单次读取量，不是数据权限控制。
- 日志默认存在终局 JSON 与 JSONL 中，可能包含 prompt、任务错误和秘密。应设置宿主文件权限、日志保留策略；分享 CI 日志前脱敏。
- 本项目不是已渗透测试的软件，单元测试的 403/404/405 不能替代完整的安全审计。

## 运行证据保护

`harness_run --runs-root` 创建 0700 会话目录和 0600 Manifest/Trace/Report，以原子替换写入终局结果；默认模式仍使用旧的“上次运行”路径。Manifest 中的 SHA-256 用来核对文件完整性，并非可信数字签名。只有拥有外部不可修改的签名/备份系统才能防止攻击者同时篡改内容与摘要。意外断电可能留下 `running` 记录，当前没有故障续跑机制。详见 [会话文档](run-sessions.md)。

## 上线前至少还缺少

独立 Unix UID / namespace、容器权限隔离、端口认证授权/审计、rootless Docker、真实 cgroup 进程创建原子约束、任务来源签名/白名单、密钥 Vault、超时副作用幂等保证、持久化日志轮转与备份、实际 FUSE/Docker 渗透测试、跨 Agent 严格租户边界、Wayland/GPUI 人机测试。

升级这些机制后，应分别提供独立负面测试与实机记录，不能只更新“支持”表述。
