"""Read-only localhost dashboard for AgentOS reports and live JSONL traces.

No third-party dependencies. Never executes tasks, accepts commands, or exposes
arbitrary filesystem paths. Run with --report/--trace paths selected by the
local user; browsers cannot choose paths through the HTTP API.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

MAX_REPORT = 8 * 1024 * 1024
MAX_TRACE = 2 * 1024 * 1024
MAX_EVENTS = 4000
UI_DIR = Path(__file__).resolve().parent.parent / "ui"
ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}
STATES = {"pending", "running", "succeeded", "failed", "blocked"}
TASK_ID = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]{0,63}$")


def read_report(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    with path.open("rb") as file:
        data = file.read(MAX_REPORT + 1)
    if len(data) > MAX_REPORT:
        raise ValueError("report exceeds 8 MiB")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("report must be an object")
    return value


def read_trace(path: Path | None) -> list[dict]:
    if path is None or not path.is_file():
        return []
    # Bounded tail: avoids O(size of all historical traces) on every poll.
    with path.open("rb") as file:
        file.seek(0, os.SEEK_END)
        end = file.tell()
        start = max(0, end - MAX_TRACE)
        file.seek(start)
        data = file.read(MAX_TRACE)
    if start:
        pos = data.find(b"\n")
        data = data[pos + 1:] if pos >= 0 else b""
    events: list[dict] = []
    for line in data.split(b"\n"):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            # A live appender may be halfway through a line.
            continue
        if isinstance(event, dict) and isinstance(event.get("event"), str):
            events.append(event)
    return events[-MAX_EVENTS:]


def build_state(report: dict, events: list[dict]) -> dict:
    """Merge live trace and final report. Report fields win for completed runs."""
    dag: dict[str, dict] = {}
    tasks: dict[str, dict] = {}
    declared_by: dict[str, str] = {}
    for event in events:
        task_id = event.get("task")
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
            continue
        kind = event["event"]
        if kind in ("admitted", "declared"):
            entry = dag.setdefault(task_id, {})
            for name in ("kind", "tenant", "priority", "cpu_units", "memory_mib", "deps"):
                if name in event:
                    entry[name] = event[name]
            tasks.setdefault(task_id, {"id": task_id, "status": "pending"})
            if kind == "declared" and isinstance(event.get("parent"), str):
                declared_by[task_id] = event["parent"]
        elif kind == "started":
            tasks.setdefault(task_id, {"id": task_id})["status"] = "running"
            tasks[task_id]["started_ns"] = event.get("time_ns")
        elif kind in ("finished", "blocked"):
            result = tasks.setdefault(task_id, {"id": task_id})
            result["status"] = event.get("status", "blocked") if kind == "finished" else "blocked"
            result["elapsed_s"] = event.get("elapsed_s", 0)
            result["attempts"] = event.get("attempts", 0)
            result["error"] = event.get("error", "dependency failed" if kind == "blocked" else "")
            result["resource_metrics"] = event.get("resource_metrics", {})
            result["finished_ns"] = event.get("time_ns")

    raw_dag = report.get("dag", {})
    if isinstance(raw_dag, dict):
        for task_id, spec in raw_dag.items():
            if isinstance(task_id, str) and TASK_ID.fullmatch(task_id) and isinstance(spec, dict):
                dag[task_id] = spec

    raw_tasks = report.get("tasks", {})
    if isinstance(raw_tasks, dict):
        for task_id, result in raw_tasks.items():
            if isinstance(task_id, str) and TASK_ID.fullmatch(task_id) and isinstance(result, dict):
                tasks[task_id] = result

    sources = report.get("declared_by", {})
    if isinstance(sources, dict):
        for key, value in sources.items():
            if isinstance(key, str) and isinstance(value, str):
                declared_by[key] = value

    # The old report format may not have DAG metadata; still render each task.
    for task_id in tasks:
        dag.setdefault(task_id, {})
    counts = {state: 0 for state in STATES}
    for task in tasks.values():
        status = task.get("status")
        if status in counts:
            counts[status] += 1
    return {
        "schema": 1, "tasks": tasks, "dag": dag,
        "declared_by": declared_by, "events": events,
        "counts": counts, "total": len(tasks),
        "isolation": report.get("isolation", "trace-only"),
        "budget": report.get("budget", {}),
        "context": report.get("context", {}),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }


def create_handler(report_path: Path | None, trace_path: Path | None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AgentOS-HarnessUI/0.1"

        def _send(self, code: int, content: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; connect-src 'self'; "
                             "style-src 'self'; script-src 'self'; "
                             "img-src 'self' data:; object-src 'none'; "
                             "base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/api/state":
                try:
                    data = build_state(read_report(report_path), read_trace(trace_path))
                    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
                    self._send(200, payload, "application/json; charset=utf-8")
                except (ValueError, OSError, UnicodeError) as exc:
                    self._send(500, json.dumps({"error": str(exc)}).encode(),
                               "application/json; charset=utf-8")
            elif path == "/healthz":
                self._send(200, b'{"ok":true}', "application/json; charset=utf-8")
            elif path in ROUTES:
                filename, content_type = ROUTES[path]
                try:
                    content = (UI_DIR / filename).read_bytes()
                except OSError:
                    self._send(500, b"UI asset missing", "text/plain; charset=utf-8")
                    return
                self._send(200, content, content_type)
            else:
                self._send(404, b"Not found", "text/plain; charset=utf-8")

        def do_POST(self) -> None:
            self._send(405, b"Read-only dashboard", "text/plain; charset=utf-8")

        def log_message(self, format: str, *args) -> None:
            # No request or query strings are written to logs.
            pass

    return Handler


def start_server(report: Path | None, trace: Path | None, port: int = 8765):
    """Return a server that the caller can run/shut down for tests."""
    return ThreadingHTTPServer(("127.0.0.1", port), create_handler(report, trace))


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentOS Harness UI (local, read-only)")
    parser.add_argument("--report", type=Path, help="final AgentOS JSON report")
    parser.add_argument("--trace", type=Path, help="live JSONL trace")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not args.report and not args.trace:
        parser.error("supply at least --report or --trace")
    if not 0 <= args.port <= 65535:
        parser.error("port must be in range 0–65535")
    server = start_server(args.report, args.trace, args.port)
    address = server.server_address
    print(f"Harness UI: http://127.0.0.1:{address[1]}", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
