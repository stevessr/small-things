# 系统实验复现协议与结果模板

目标：让其他贡献者拿到同一个 commit、实验计划和命令后能重现测试条件。**记录结果不等于声称结果已获得**；空白模板中不填入虚构性能数字。

## 1. 环境记录

每个实验单独建一个 `runs/<date>-<shortsha>/`（本地目录，不建议提交含隐私的结果）。保留以下信息：

| 字段 | 填写方法 |
| --- | --- |
| Git commit | `git rev-parse HEAD` |
| Linux / Kernel | `cat /etc/os-release`; `uname -r` |
| Python / Node / Rust | `python3 --version`; `node --version`; `rustc --version`（按实际后端） |
| CPU / Memory / GPU | `lscpu`; `free -h`; 需真实 GPU 时使用对应设备查询 |
| Session | Wayland/X11、DPI、屏幕尺寸、是否 headless（GPUI 专项） |
| Executor | `host` 或 `layerfs`，是否真实 Docker、SDK/daemon/Store 版本 |
| Limits | CPU/memory/max_tasks、cgroup 委派状态、LayerFS 是否有容器级限制 |
| Workload | 完整 Plan JSON、工作目录、输入样本大小、重试超时、随机种子 |
| Evidence | Report、JSONL Trace、测试命令及标准输出/失败日志 |

推荐使用 `--runs-root .agentos/runs` 保存每次单独实验的状态与完整性校验文件；具体步骤见 [会话保留与核验](run-sessions.md)。任务结果退出码不等同于记录完整性，SHA-256 只能检测意外损坏，不构成签名。

## 2. 复现步骤（Host）

```bash
cd small-things/agentos
python3 -m agentos.doctor --backend host --ui web --format json > /tmp/agentos-doctor.json
python3 -m agentos.plan_lint examples/demo.json --format json > /tmp/agentos-plan.json
python3 -m unittest discover -s tests -v
python3 -m agentos.cli examples/demo.json \
  --report /tmp/agentos-eval-report.json --trace /tmp/agentos-eval-trace.jsonl
python3 -m bench.benchmark \
  --tasks 8 --parallel 4 --sleep 0.05 --trials 5 --output /tmp/agentos-bench.json
```

`agentos.cli` 的 `--trace` **追加**到文件；多次运行应使用新的文件名，或先归档旧文件。使用同一 OS/CPU、同一任务负载比较串行与并行；不要只报告最快一次。

## 3. 分组与消融

| 组别 | 描述 | 可观测指标 | 可直接执行？ |
| --- | --- | --- | --- |
| A | 同一 DAG 的串行资源预算 | end-to-end、失败率 | 是 |
| B | 同一 DAG 的并行资源预算 | end-to-end、失败率 | 是 |
| C | Host + SQLite/zlib 文本上下文命中 | context hit 与字节统计 | 需构造重复上下文任务 |
| D | Host + 已委派 cgroup v2 | 内存/CPU/PIDs | 需要真实内核和 systemd Delegate |
| E | LayerFS Commit/FC 路径 | FC Commit、恢复正确率、IO 延迟 | 需要真实 SDK/Docker/FUSE |
| F | GPUI 动态 DAG 与 4K/多屏 | 图形正确性、事件延迟、页数 | 需要真实 Wayland/X11 显示 |

`bench.benchmark` 使用 sleep 任务，这只展示调度器的并发效果，不能等同于真实 LLM 的吞吐、时延、token/s 或 KV Cache 共享。

## 4. 结果记录空表

| 实验组 | 运行次数 | p50 (s) | p95 (s) | 内存峰值 (MiB) | 失败率 | 备注 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| A | — | — | — | — | — | 待测 |
| B | — | — | — | — | — | 待测 |
| C | — | — | — | — | — | 待测 |
| D | — | — | — | — | — | 待测 |
| E | — | — | — | — | — | 待测 |
| F | — | — | — | — | — | 待测 |

必须注明样本数量、预热次数、时间戳测量范围、异常值处理和置信区间算法。无法获得某内核指标时标记为“未测得”，不能写 0。CI 环境中的测试通过率与真实硬件性能数据分开报告。

## 5. 发布/答辩证据门槛

- “调度器可正确传播失败”：关联具体 Host DAG 单测、CI SHA。
- “支持 FC 文件回退”：区分 Fake SDK 协议验证与实际 Docker/FUSE 故障注入；展示恢复前后 Branch 与不可变 Commit。
- “GPU/LLM 加速”：必须有真实模型、tokenizer、显存/RSS 和可重复 workload，现阶段**不得声称已实现**。
- “GPUI 屏幕适配”：CI 编译通过之外，需提供至少不同尺寸/缩放/多屏环境的人机测试记录。

文档更新时同时更新 [测试矩阵](testing.md) 和 [能力边界](capabilities.md)。
