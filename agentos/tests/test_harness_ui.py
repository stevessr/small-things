"""Harness UI: state synthesis, robust tail parsing, HTTP security and live stream."""
from __future__ import annotations

import json
import os
import sys
import time
from importlib.resources import files
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agentos.harness_ui import (MAX_REPORT, build_state, read_report, read_trace, start_server)


class HarnessModelTests(unittest.TestCase):
    def test_legacy_report_and_trace_merge(self):
        events = [
            {"event": "admitted", "time_ns": 2, "task": "root",
             "kind": "model", "deps": [], "tenant": "a"},
            {"event": "declared", "time_ns": 3, "task": "child", "parent": "root",
             "deps": ["root"], "kind": "tool"},
            {"event": "started", "time_ns": 4, "task": "root"},
            {"event": "finished", "time_ns": 8, "task": "root", "status": "succeeded",
             "elapsed_s": 0.3},
            {"event": "started", "time_ns": 9, "task": "child"},
        ]
        state = build_state({}, events)
        self.assertEqual(state["total"], 2)
        self.assertEqual(state["counts"]["running"], 1)
        self.assertEqual(state["counts"]["succeeded"], 1)
        self.assertEqual(state["dag"]["child"]["deps"], ["root"])
        self.assertEqual(state["declared_by"]["child"], "root")
        self.assertEqual(state["tasks"]["child"]["status"], "running")

        report = {"tasks": {"child": {"id": "child", "status": "failed", "stderr": "boom"}},
                  "dag": {"child": {"deps": ["root"], "tenant": "a"}},
                  "isolation": "layerfs"}
        final = build_state(report, events)
        self.assertEqual(final["counts"]["failed"], 1)
        self.assertEqual(final["counts"]["running"], 0)
        self.assertEqual(final["isolation"], "layerfs")
        self.assertEqual(final["tasks"]["child"]["stderr"], "boom")

    def test_trace_skips_malformed_line_and_invalid_tasks(self):
        with tempfile.TemporaryDirectory() as dir:
            trace = Path(dir) / "trace.jsonl"
            trace.write_bytes(b'{"event":"admitted","task":"ok"}\n'
                              b'{"event":"admitted","task":"invalid id"}\n'
                              b'broken-partial{')
            events = read_trace(trace)
            self.assertEqual(len(events), 2)
            state = build_state({}, events)
            self.assertEqual(list(state["tasks"]), ["ok"])

    def test_tail_is_bounded_and_starts_on_complete_line(self):
        with tempfile.TemporaryDirectory() as dir:
            trace = Path(dir) / "trace.jsonl"
            with trace.open("w") as f:
                for i in range(5500):
                    f.write(json.dumps({"event": "admitted", "task": "agent", "n": i,
                                        "padding": "z"*400}) + "\n")
            events = read_trace(trace)
            self.assertLessEqual(len(events), 4000)
            self.assertEqual(events[-1]["n"], 5499)
            self.assertGreater(events[0]["n"], 0)

    def test_oversized_report_rejected(self):
        with tempfile.TemporaryDirectory() as dir:
            path = Path(dir) / "huge.json"
            path.write_bytes(b" " * (MAX_REPORT + 1))
            with self.assertRaisesRegex(ValueError, "exceeds"):
                read_report(path)

    def test_packaged_assets_are_importable(self):
        assets = files("agentos").joinpath("ui")
        self.assertIn("<title>AgentOS", assets.joinpath("index.html").read_text())
        self.assertIn("function renderGraph", assets.joinpath("app.js").read_text())
        self.assertIn(".sidebar", assets.joinpath("styles.css").read_text())

    def test_no_files_is_empty_state(self):
        self.assertEqual(read_report(None), {})
        self.assertEqual(read_trace(None), [])
        self.assertEqual(build_state({}, [])["total"], 0)


class HarnessHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.report = Path(cls.temp.name) / "report.json"
        cls.trace = Path(cls.temp.name) / "trace.jsonl"
        cls.trace.write_text(json.dumps({"event": "admitted", "task": "start",
                                         "deps": []}) + "\n")
        cls.server = start_server(cls.report, cls.trace, port=0)
        cls.host = "http://127.0.0.1:" + str(cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.temp.cleanup()

    def setUp(self):
        # HTTP cases share a server, but must not share test-created reports.
        self.report.unlink(missing_ok=True)
        self.trace.write_text(json.dumps({"event": "admitted",
                                          "task": "start", "deps": []}) + "\n")

    def test_assets_health_and_headers(self):
        for path, mime in [("/", "text/html"), ("/app.js", "text/javascript"),
                           ("/styles.css", "text/css"), ("/healthz", "application/json")]:
            with urlopen(self.host + path, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(mime, response.headers["Content-Type"])
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
                self.assertTrue(response.read())

    def test_live_updates_without_server_restart(self):
        with urlopen(self.host + "/api/state", timeout=5) as response:
            initial = json.load(response)
        self.assertEqual(initial["counts"]["pending"], 1)
        with self.trace.open("a") as file:
            file.write(json.dumps({"event": "started", "task": "start", "time_ns": 5}) + "\n")
        with urlopen(self.host + "/api/state", timeout=5) as response:
            next_state = json.load(response)
        self.assertEqual(next_state["counts"]["running"], 1)
        self.report.write_text(json.dumps({"tasks": {
            "start": {"id": "start", "status": "succeeded", "filesystem_commit": "c1"}
        }, "dag": {"start": {"deps": []}}}))
        with urlopen(self.host + "/api/state", timeout=5) as response:
            final = json.load(response)
        self.assertEqual(final["counts"]["succeeded"], 1)
        self.assertEqual(final["tasks"]["start"]["filesystem_commit"], "c1")

    def test_dns_rebinding_host_is_refused(self):
        request = Request(self.host + "/api/state", headers={"Host": "attacker.example"})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 403)

    @unittest.skipUnless(sys.platform == "linux", "inotify is Linux only")
    def test_inotify_pushes_after_report_atomic_rename(self):
        # Live SSE first signals initial snapshot, then real filesystem mutation.
        with urlopen(self.host + "/api/changes", timeout=10) as stream:
            self.assertEqual(stream.headers.get_content_type(), "text/event-stream")
            first = stream.readline().decode()
            self.assertTrue(first.startswith("data: "))
            stream.readline()  # blank event delimiter
            temp = self.report.with_name("report.new")
            temp.write_text(json.dumps({"tasks": {"start": {"status": "succeeded"}}}))
            os.replace(temp, self.report)
            update = stream.readline().decode()
            self.assertTrue(update.startswith("data: "), msg=update)
            self.assertNotEqual(update, first)

    def test_summary_and_lazy_task_detail(self):
        self.report.write_text(json.dumps({
            "tasks": {"start": {"id": "start", "status": "succeeded",
                                "stdout": "private large log", "stderr": "error details",
                                "resource_metrics": {"memory_peak": 123}}},
            "dag": {"start": {"deps": [], "kind": "tool"}}
        }))
        with urlopen(self.host + "/api/state?view=summary", timeout=5) as response:
            summary = json.load(response)
        self.assertNotIn("stdout", summary["tasks"]["start"])
        self.assertNotIn("resource_metrics", summary["tasks"]["start"])
        self.assertEqual(summary["events"], [])
        with urlopen(self.host + "/api/task/start", timeout=5) as response:
            detail = json.load(response)
        self.assertEqual(detail["task"]["stdout"], "private large log")
        self.assertEqual(detail["task"]["resource_metrics"]["memory_peak"], 123)
        self.assertEqual(detail["spec"]["kind"], "tool")

    def test_paginated_summary_preserves_global_counts_and_order(self):
        # This case tests a finalized report; don't merge the class's default
        # live "start" fixture into its unrelated 135-task DAG.
        self.trace.write_text("")
        tasks = {
            f"task_{n:03d}": {
                "id": f"task_{n:03d}", "status": "succeeded" if n % 2 else "failed",
                "stdout": "x" * 200, "stderr": "private", "resource_metrics": {"cpu": n}
            } for n in range(135)
        }
        dag = {
            key: {"deps": [] if i == 0 else ["task_000"], "kind": "tool"}
            for i, key in enumerate(tasks)
        }
        self.report.write_text(json.dumps({
            "tasks": tasks, "dag": dag, "declared_by": {"task_050": "task_000"}
        }))
        for offset, expected in [(0, 40), (40, 40), (80, 40), (120, 15), (135, 0)]:
            with self.subTest(offset=offset):
                with urlopen(self.host + f"/api/state?view=summary&offset={offset}&limit=40",
                             timeout=5) as response:
                    state = json.load(response)
                self.assertEqual(state["total"], 135)
                self.assertEqual(len(state["tasks"]), expected)
                self.assertEqual(set(state["dag"]), set(state["tasks"]))
                self.assertEqual(state["counts"]["failed"], 68)
                self.assertEqual(state["counts"]["succeeded"], 67)
                self.assertEqual(state["events"], [])
                for item in state["tasks"].values():
                    self.assertNotIn("stdout", item)
                    self.assertNotIn("stderr", item)
                    self.assertNotIn("resource_metrics", item)
        with urlopen(self.host + "/api/state?view=summary&offset=50&limit=1",
                     timeout=5) as response:
            page = json.load(response)
        self.assertEqual(list(page["tasks"]), ["task_050"])
        self.assertEqual(page["declared_by"], {"task_050": "task_000"})
        with urlopen(self.host + "/api/state?view=summary", timeout=5) as response:
            legacy = json.load(response)
        self.assertEqual(len(legacy["tasks"]), 135)

    def test_pagination_query_rejects_bad_offsets_and_limits(self):
        for suffix in (
            "offset=-1&limit=40", "offset=0&limit=0",
            "offset=0&limit=41", "offset=10001&limit=1",
            "offset=01foo&limit=40", "offset=0&limit=x",
            "offset=0", "limit=40", "offset=0&offset=40&limit=20",
            "offset=0&limit=20&limit=2",
        ):
            with self.subTest(query=suffix), self.assertRaises(HTTPError) as error:
                urlopen(self.host + "/api/state?view=summary&" + suffix, timeout=5)
            self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error:
            urlopen(self.host + "/api/state?offset=0&limit=10", timeout=5)
        self.assertEqual(error.exception.code, 400)

    def test_report_error_is_500_even_when_paginated(self):
        self.report.write_bytes(b" " * (MAX_REPORT + 1))
        with self.assertRaises(HTTPError) as error:
            urlopen(self.host + "/api/state?view=summary&offset=0&limit=40", timeout=5)
        self.assertEqual(error.exception.code, 500)

    def test_lazy_detail_rejects_unregistered_task(self):
        for name in ["nonexistent", "..", "invalid id"]:
            with self.assertRaises(HTTPError):
                urlopen(self.host + "/api/task/" + name.replace(" ", "%20"), timeout=5)

    def test_read_only_and_unknown_paths(self):
        for path in ("/../../etc/passwd", "/nonexistent", "/api/commands",
                     "/agentos/README.md"):
            with self.assertRaises(HTTPError) as caught:
                urlopen(self.host + path, timeout=5)
            self.assertEqual(caught.exception.code, 404)
        request = Request(self.host + "/api/state", method="POST", data=b"{}")
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 405)


if __name__ == "__main__":
    unittest.main()
