"""Execute an AgentOS plan with an event-driven, local, read-only dashboard.

Use --runs-root to retain isolated, timestamped run artifacts. No browser API
can create or modify sessions. Historical paths are never reused in that mode.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import threading
import time
import webbrowser
from pathlib import Path

from .artifacts import atomic_json, create_run_dir, file_sha256, init_trace, utc_now
from .core import AgentRuntime
from .harness_ui import start_server
from .layerfs import LayerFSRuntime
from .models import Status
from .plan_lint import read_plan


def atomic_report(path: Path, value: dict) -> None:
    """Backward-compatible name used by existing tests and integrations."""
    atomic_json(path, value)


def main() -> int:
    parser = argparse.ArgumentParser(description="AgentOS runner with local read-only UI")
    parser.add_argument("plan", type=Path)
    parser.add_argument("--filesystem", choices=["host", "layerfs"], default="host")
    parser.add_argument("--report", type=Path, help="final JSON (default: .agentos/last-report.json)")
    parser.add_argument("--trace", type=Path, help="JSONL (default: .agentos/last-trace.jsonl)")
    parser.add_argument("--runs-root", type=Path,
                        help="create a new private session directory for every run")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-browser", action="store_true", help="open the localhost UI")
    parser.add_argument("--exit-after-run", action="store_true",
                        help="stop serving after completion (for CI)")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be 0–65535")
    if args.runs_root is not None and (args.report is not None or args.trace is not None):
        parser.error("--runs-root cannot be combined with --report or --trace")
    try:
        tasks, budget, _ = read_plan(args.plan)
        digest = hashlib.sha256(args.plan.read_bytes()).hexdigest()
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Invalid AgentOS plan: {exc}\n")
    try:
        run_dir = create_run_dir(args.runs_root) if args.runs_root is not None else None
    except OSError as exc:
        parser.exit(2, f"Cannot create run directory: {exc}\n")
    report = (run_dir / "report.json" if run_dir else
              args.report or Path(".agentos/last-report.json"))
    trace = (run_dir / "trace.jsonl" if run_dir else
             args.trace or Path(".agentos/last-trace.jsonl"))
    if report.resolve() == trace.resolve():
        parser.error("--report and --trace must be different files")
    manifest = run_dir / "manifest.json" if run_dir else None

    # Validate and bind the HTTP listener before destroying any old output.
    # The runtime's admission events are buffered until after listener setup.
    try:
        report.parent.mkdir(parents=True, exist_ok=True)
        trace.parent.mkdir(parents=True, exist_ok=True)
        server = start_server(report, trace, args.port)
    except OSError as exc:
        parser.exit(2, f"Cannot bind localhost Harness UI: {exc}\n")
    try:
        if args.filesystem == "layerfs":
            runtime = LayerFSRuntime(tasks, budget, trace_path=None)
        else:
            runtime = AgentRuntime(tasks, budget, trace_path=None)
    except (ValueError, OSError, RuntimeError) as exc:
        server.server_close()
        parser.exit(2, f"Cannot initialize AgentOS Runtime: {exc}\n")

    # New trace is visible as one complete file; future events are appended.
    # Runtime construction did not touch a previous run's files.
    try:
        init_trace(trace, runtime.events)
        runtime.trace_path = str(trace)
        report.unlink(missing_ok=True)
    except OSError as exc:
        server.server_close()
        parser.exit(2, f"Cannot prepare run artifacts: {exc}\n")

    record = None
    if manifest is not None:
        record = {
            "schema": 1,
            "run_id": run_dir.name,
            "status": "running",
            "exit_code": None,
            "started_utc": utc_now(),
            "finished_utc": None,
            "filesystem": args.filesystem,
            "plan_sha256": digest,
            "task_count_initial": len(tasks),
            "report": "report.json",
            "trace": "trace.jsonl",
        }
        try:
            atomic_json(manifest, record)
        except OSError as exc:
            server.server_close()
            parser.exit(2, f"Cannot write run manifest: {exc}\n")

    thread = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.25}, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Harness UI: {url}", flush=True)
    if run_dir is not None:
        print(f"Run artifacts: {run_dir}", flush=True)
    if args.open_browser:
        webbrowser.open(url)
    code = 2
    try:
        try:
            results = asyncio.run(runtime.run())
            code = 0 if all(value.status == Status.SUCCEEDED
                            for value in results.values()) else 1
            atomic_report(report, runtime.report())
        except (Exception, KeyboardInterrupt) as exc:
            code = 130 if isinstance(exc, KeyboardInterrupt) else 2
            print(f"AgentOS run interrupted/failed: {type(exc).__name__}: {exc}",
                  flush=True)
            atomic_report(report, runtime.report())
        finally:
            if record is not None:
                record["status"] = ("succeeded" if code == 0 else
                                    "failed" if code == 1 else
                                    "interrupted" if code == 130 else "error")
                record["exit_code"] = code
                record["finished_utc"] = utc_now()
                # Digests are integrity checks, not cryptographic signatures.
                record["report_sha256"] = file_sha256(report) if report.is_file() else None
                record["trace_sha256"] = file_sha256(trace) if trace.is_file() else None
                atomic_json(manifest, record)

        print(f"AgentOS finished: exit={code}; report={report}; trace={trace}",
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
        thread.join(timeout=3)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
