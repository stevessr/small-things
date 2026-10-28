# AgentOS Harness 架构决策记录（ADR）

ADR 记录为什么选择当前实现，而不仅是调用接口的方法。每条条目都包含背景、决策、取舍、验证与可替代方案；已接受的 ADR 不表示相关实现已达到生产标准。

| ID | 状态 | 决策 |
| --- | --- | --- |
| [ADR-0001](0001-host-layerfs-backends.md) | 已接受，原型范围 | 共用 DAG 控制面，保留独立 Host / LayerFS 执行后端 |
| [ADR-0002](0002-event-driven-observability.md) | 已接受，原型范围 | inotify/SSE 只通知变化，UI 从只读快照拉取数据 |
| [ADR-0003](0003-nondestructive-checkpoints.md) | 已接受，原型范围 | FC 只 fork 新 Branch，不原地改写现有历史 |
| [ADR-0004](0004-retained-run-evidence.md) | 已接受，原型范围 | 独立运行会话与不覆盖历史的原子报告 |
| [ADR-0005](0005-ordered-control-and-evidence.md) | 已接受，Supervisor 事实范围 | 有序控制证据、诚实游标与 Replay ≠ Resume |

新增重要架构变化时需记录新 ADR，标明以前的 ADR 是否被替代。真实环境尚待验证的假设需保留在[能力成熟度说明](../capabilities.md)，不得通过 ADR “决定”直接升级为已实现能力。
