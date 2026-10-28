"""Run declarative multi-Agent DAG plans on Linux/openEuler."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .core import AgentRuntime
from .layerfs import LayerFSRuntime
from .models import AgentSpec, Budget, Status


def main() -> int:
    parser = argparse.ArgumentParser(description="AgentOS cgroup-aware multi-agent harness")
    parser.add_argument("plan", type=Path, help="JSON execution plan")
    parser.add_argument("--context-db", default=":memory:", help="SQLite path for cross-run context reuse")
    parser.add_argument("--trace", help="append JSONL lifecycle events to path")
    parser.add_argument("--report", help="write final JSON report to path")
    parser.add_argument("--cgroup-root", help="writable, controller-delegated cgroup v2 directory")
    parser.add_argument("--filesystem", choices=["host", "layerfs"], default="host",
                        help="host subprocesses or LayerFS Docker workspaces")
    parser.add_argument("--require-cgroup", action="store_true", help="fail rather than using rlimit fallback")
    args = parser.parse_args()

    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        specs = [AgentSpec.parse(raw) for raw in plan["tasks"]]
        if args.filesystem == "layerfs":
            if args.cgroup_root or args.require_cgroup:
                raise ValueError("--cgroup-root and --require-cgroup do not apply to LayerFS sandbox execution")
            if args.context_db != ":memory:":
                raise ValueError("--context-db belongs to the host IPC backend, not LayerFS")
            runtime = LayerFSRuntime(specs, Budget.parse(plan.get("budget", {})),
                                     trace_path=args.trace)
        else:
            runtime = AgentRuntime(specs, Budget.parse(plan.get("budget", {})),
                                   context_path=args.context_db, cgroup_root=args.cgroup_root,
                                   require_cgroup=args.require_cgroup, trace_path=args.trace)
        results = asyncio.run(runtime.run())
        report = runtime.report()
        rendered = json.dumps(report, ensure_ascii=False, indent=2)
        if args.report:
            report_path = Path(args.report)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0 if all(result.status == Status.SUCCEEDED for result in results.values()) else 1
    except (ValueError, KeyError, RuntimeError, OSError) as exc:
        parser.exit(2, f"AgentOS configuration/runtime error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
