"""Compare identical subprocess DAGs with one and N admitted CPU slots.

This is an I/O/latency-oriented synthetic scheduler benchmark, NOT a comparison
against LangGraph or a measurement of LLM token-generation acceleration.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
import time
from pathlib import Path

from agentos import AgentRuntime, AgentSpec, Budget, Status
from agentos.context import ContextStore


async def one_run(task_count: int, slots: int, sleep_s: float) -> float:
    specs = [AgentSpec.parse({
        "id": f"agent-{n}", "argv": [sys.executable, "-c",
        f"import time; time.sleep({sleep_s!r})"], "memory_mib": 128
    }) for n in range(task_count)]
    engine = AgentRuntime(specs, Budget(cpu_units=slots, memory_mib=slots * 128))
    t0 = time.perf_counter()
    results = await engine.run()
    elapsed = time.perf_counter() - t0
    if any(x.status != Status.SUCCEEDED for x in results.values()):
        raise RuntimeError("synthetic workload failed; benchmark invalid")
    return elapsed


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    # Nearest-rank percentile, clearly defined for small samples.
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * p) - 1))]


async def measure(task_count: int, parallel: int, sleep_s: float, trials: int) -> dict:
    serial_samples = []
    parallel_samples = []
    for _ in range(trials):
        # Alternating order partially reduces warmup/thermal bias.
        if len(serial_samples) % 2:
            parallel_samples.append(await one_run(task_count, parallel, sleep_s))
            serial_samples.append(await one_run(task_count, 1, sleep_s))
        else:
            serial_samples.append(await one_run(task_count, 1, sleep_s))
            parallel_samples.append(await one_run(task_count, parallel, sleep_s))

    context = ContextStore()
    try:
        sample = "system audit trace and shared prompt segment " * 500
        compressed = context.put("team-1", "prompt", sample)
        for _ in range(task_count - 1):
            if context.get("team-1", "prompt") != sample:
                raise RuntimeError("context content mismatch")
        if context.get("team-2", "prompt") is not None:
            raise RuntimeError("context tenant boundary broken")
        cache = context.stats()
    finally:
        context.close()

    serial_med = statistics.median(serial_samples)
    parallel_med = statistics.median(parallel_samples)
    return {
        "workload": {"type": "synthetic subprocess sleep (I/O latency)",
                     "tasks": task_count, "parallel_slots": parallel,
                     "sleep_s": sleep_s, "trials": trials},
        "serial_makespan_s": {"median": round(serial_med, 5),
                              "p95_nearest_rank": round(percentile(serial_samples, 0.95), 5),
                              "samples": [round(v, 5) for v in serial_samples]},
        "parallel_makespan_s": {"median": round(parallel_med, 5),
                                "p95_nearest_rank": round(percentile(parallel_samples, 0.95), 5),
                                "samples": [round(v, 5) for v in parallel_samples]},
        "speedup_median": round(serial_med / parallel_med, 3),
        "context": {**cache, **compressed},
        "note": "Not GPU KV-cache sharing, token throughput, or comparison with external frameworks."
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=int, default=8)
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--sleep", type=float, default=0.1)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not (2 <= args.tasks <= 100 and 1 <= args.parallel <= 64 and
            args.parallel <= args.tasks and 0 < args.sleep <= 10 and 1 <= args.trials <= 30):
        parser.error("invalid workload parameters")
    report = asyncio.run(measure(args.tasks, args.parallel, args.sleep, args.trials))
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
