"""Run an AgentOS task plan with the live local dashboard already attached."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
import time
import webbrowser
from pathlib import Path

from .core import AgentRuntime
from .harness_ui import start_server
from .layerfs import LayerFSRuntime
from .models import AgentSpec, Budget, Status
from .plan_lint import read_plan


def atomic_report(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + str(os.getpid()))
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="AgentOS harness runner with live read-only UI")
    parser.add_argument("plan", type=Path)
    parser.add_argument("--filesystem", choices=["host", "layerfs"], default="host")
    parser.add_argument("--report", type=Path, default=Path(".agentos/last-report.json"))
    parser.add_argument("--trace", type=Path, default=Path(".agentos/last-trace.jsonl"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-browser", action="store_true", help="open the localhost UI")
    parser.add_argument("--exit-after-run", action="store_true",
                        help="stop serving after completion (for CI)")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be 0–65535")
    if args.report.resolve() == args.trace.resolve():
        parser.error("--report and --trace must be different files")
    try:
        tasks, budget, _ = read_plan(args.plan)
        if args.filesystem == "layerfs":
            runtime = LayerFSRuntime(tasks, budget, trace_path=str(args.trace))
        else:
            runtime = AgentRuntime(tasks, budget, trace_path=str(args.trace))
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        parser.exit(2, f"Invalid AgentOS plan: {exc}\n")

    args.trace.parent.mkdir(parents=True, exist_ok=True)
    # Truncate old events before launching the UI; preserve preflight admission
    # events already in memory and flush them into the new live trace.
    events = runtime.events[:]
    args.trace.write_text("", encoding="utf-8")
    for event in events:
        with args.trace.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    args.report.unlink(missing_ok=True)
    try:
        server = start_server(args.report, args.trace, args.port)
    except OSError as exc:
        parser.exit(2, f"Cannot bind localhost Harness UI: {exc}\n")
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.25},
                              daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Harness UI: {url}", flush=True)
    if args.open_browser:
        webbrowser.open(url)
    code = 1
    try:
        try:
            result = asyncio.run(runtime.run())
            code = 0 if all(item.status == Status.SUCCEEDED
                            for item in result.values()) else 1
            atomic_report(args.report, runtime.report())
        except (ValueError, OSError, RuntimeError) as exc:
            print(f"AgentOS run failed: {exc}", flush=True)
            atomic_report(args.report, runtime.report())
            code = 2
        print(f"AgentOS finished: exit={code}; report={args.report}; trace={args.trace}",
              flush=True)
        if not args.exit_after_run:
            print("Dashboard remains available. Press Ctrl+C to close.", flush=True)
            try:
                while True:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
