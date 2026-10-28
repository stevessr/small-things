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
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from .change_watch import ChangeWatch

MAX_REPORT = 8 * 1024 * 1024
MAX_TRACE = 2 * 1024 * 1024
MAX_EVENTS = 4000
UI_DIR = Path(__file__).resolve().parent / "ui"
ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}
STATES = {"pending", "running", "succeeded", "failed", "blocked"}
TASK_ID = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]{0,63}$")
MAX_PAGE_SIZE = 40
MAX_PAGE_OFFSET = 10000


class PageQueryError(ValueError):
    """Invalid client pagination query; report parsing errors stay HTTP 500."""


SUMMARY_FIELDS = frozenset({
    "id", "status", "elapsed_s", "attempts", "exit_code",
    "filesystem_branch", "filesystem_commit",
})


def paginate_summary(state: dict, query: dict[str, list[str]]) -> dict:
    """Project a bounded page of task summaries without changing global counts.

    Pagination is opt-in; existing GET /api/state?view=summary clients still
    receive the full summary. Task IDs are sorted, so independent clients see
    consistent deterministic pages for the same snapshot.
    """
    # Cached source snapshots are immutable to readers. Projection may replace
    # top-level maps, but must not modify the shared object.
    state = state.copy()
    page_requested = "offset" in query or "limit" in query
    if not page_requested:
        state["events"] = []
        state["tasks"] = {
            key: {field: value for field, value in task.items()
                  if field in SUMMARY_FIELDS}
            for key, task in state["tasks"].items()
        }
        return state

    if "offset" not in query or "limit" not in query:
        raise PageQueryError("offset and limit must be supplied together")
    if any(len(query[key]) != 1 for key in ("offset", "limit")):
        raise PageQueryError("offset and limit must each occur exactly once")
    raw_offset, raw_limit = query["offset"][0], query["limit"][0]
    if not raw_offset.isascii() or not raw_offset.isdecimal() or (
            not raw_limit.isascii() or not raw_limit.isdecimal()):
        raise PageQueryError("offset and limit must be unsigned decimal integers")
    offset, limit = int(raw_offset), int(raw_limit)
    if offset > MAX_PAGE_OFFSET or not 1 <= limit <= MAX_PAGE_SIZE:
        raise PageQueryError("offset must be <= 10000 and limit within 1–40")

    keys = sorted(state["tasks"])
    selected = keys[offset:offset + limit]
    state["tasks"] = {
        key: {field: value for field, value in state["tasks"][key].items()
              if field in SUMMARY_FIELDS}
        for key in selected
    }
    state["dag"] = {key: state["dag"].get(key, {}) for key in selected}
    state["declared_by"] = {
        key: state["declared_by"][key] for key in selected
        if key in state["declared_by"]
    }
    state["events"] = []
    return state


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


class SnapshotCache:
    """Per-server snapshot cache. No polling, no background refresh worker.

    Multiple GPUI/Web clients requesting the same version share a parsed
    snapshot. Stat signatures also detect changes when inotify is unavailable.
    """

    def __init__(self, report: Path | None, trace: Path | None,
                 changes: ChangeWatch):
        self.report, self.trace, self.changes = report, trace, changes
        self._lock = threading.Lock()
        self._signature_value: tuple | None = None
        self._state: dict | None = None

    @staticmethod
    def _file_key(path: Path | None) -> tuple | None:
        if path is None:
            return None
        try:
            info = path.stat()
            return (info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        except FileNotFoundError:
            return None

    def _signature(self) -> tuple:
        return (self.changes.version, self._file_key(self.report),
                self._file_key(self.trace))

    def get(self) -> dict:
        with self._lock:
            key = self._signature()
            if key == self._signature_value and self._state is not None:
                return self._state
            state = build_state(read_report(self.report), read_trace(self.trace))
            # Catch a file swap or append that races the first parse. If the
            # file keeps changing, the next request will detect the mismatch.
            next_key = self._signature()
            if next_key != key:
                state = build_state(read_report(self.report), read_trace(self.trace))
                key = next_key
            self._state, self._signature_value = state, key
            return state


def create_handler(report_path: Path | None, trace_path: Path | None,
                   changes: ChangeWatch):
    cache = SnapshotCache(report_path, trace_path, changes)

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

        def _valid_host(self) -> bool:
            # Prevent DNS rebinding from an attacker-controlled website.
            expected = "127.0.0.1:" + str(self.server.server_port)
            return self.headers.get("Host", "") == expected

        def do_GET(self) -> None:
            if not self._valid_host():
                self._send(403, b"Invalid Host", "text/plain; charset=utf-8")
                return
            path = urlsplit(self.path).path
            if path == "/api/changes":
                self._changes()
            elif path == "/api/state":
                try:
                    data = cache.get()
                    query = parse_qs(urlsplit(self.path).query)
                    if query.get("view") == ["summary"]:
                        data = paginate_summary(data, query)
                    elif "offset" in query or "limit" in query:
                        raise PageQueryError("pagination is supported only for view=summary")
                    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
                    self._send(200, payload, "application/json; charset=utf-8")
                except PageQueryError as exc:
                    self._send(400, json.dumps({"error": str(exc)}).encode(),
                               "application/json; charset=utf-8")
                except (ValueError, OSError, UnicodeError) as exc:
                    self._send(500, json.dumps({"error": str(exc)}).encode(),
                               "application/json; charset=utf-8")
            elif path.startswith("/api/task/"):
                task_id = path.removeprefix("/api/task/")
                if not TASK_ID.fullmatch(task_id):
                    self._send(404, b"Unknown task", "text/plain; charset=utf-8")
                    return
                try:
                    data = cache.get()
                    if task_id not in data["tasks"]:
                        self._send(404, b"Unknown task", "text/plain; charset=utf-8")
                        return
                    payload = json.dumps({"task": data["tasks"][task_id],
                                          "spec": data["dag"].get(task_id, {})},
                                         ensure_ascii=False, separators=(",", ":")).encode()
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

        def _changes(self) -> None:
            if not changes.active:
                self._send(503, b"Native Linux file event monitoring unavailable",
                           "text/plain; charset=utf-8")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            version = changes.version
            try:
                self.wfile.write(f"data: {version}\n\n".encode())
                self.wfile.flush()
                while changes.active:
                    next_version = changes.wait(version)
                    if not changes.active:
                        break
                    if next_version > version:
                        version = next_version
                        self.wfile.write(f"data: {version}\n\n".encode())
                    else:
                        self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def do_POST(self) -> None:
            if not self._valid_host():
                self._send(403, b"Invalid Host", "text/plain; charset=utf-8")
                return
            self._send(405, b"Read-only dashboard", "text/plain; charset=utf-8")

        def log_message(self, format: str, *args) -> None:
            # No request or query strings are written to logs.
            pass

    return Handler


def start_server(report: Path | None, trace: Path | None, port: int = 8765):
    """Return a server that the caller can run/shut down for tests."""
    watched = [path for path in (report, trace) if path is not None]
    changes = ChangeWatch(watched)

    class HarnessServer(ThreadingHTTPServer):
        daemon_threads = True

        def server_close(self) -> None:
            changes.close()
            super().server_close()

    try:
        return HarnessServer(("127.0.0.1", port), create_handler(report, trace, changes))
    except BaseException:
        changes.close()
        raise


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
