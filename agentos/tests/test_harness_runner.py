"""End-to-end CLI Harness Runner: real jobs, trace, report and live HTTP bootstrap."""
from __future__ import annotations

import json
import hashlib
import socket
import stat
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agentos.harness_run import atomic_report


class HarnessRunnerTests(unittest.TestCase):
    def test_atomic_report_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as dir:
            target = Path(dir) / "nested" / "report.json"
            atomic_report(target, {"tasks": {"x": {"status": "succeeded"}}})
            self.assertEqual(json.loads(target.read_text())["tasks"]["x"]["status"],
                             "succeeded")
            self.assertFalse(list(target.parent.glob("*.tmp*")))

    def test_live_runner_executes_real_dynamic_task_plan(self):
        with tempfile.TemporaryDirectory() as dir:
            root = Path(dir)
            report = root / "report.json"
            trace = root / "trace.jsonl"
            command = [
                sys.executable, "-m", "agentos.harness_run",
                "examples/agent-declarations.json", "--report", str(report),
                "--trace", str(trace), "--port", "0", "--exit-after-run",
            ]
            result = subprocess.run(command, cwd=Path(__file__).resolve().parent.parent,
                                    capture_output=True, text=True, timeout=20, check=False)
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("http://127.0.0.1:", result.stdout)
            data = json.loads(report.read_text())
            self.assertEqual(set(data["tasks"]),
                             {"planner", "research_a", "research_b", "synthesis"})
            self.assertTrue(all(task["status"] == "succeeded"
                                for task in data["tasks"].values()))
            self.assertEqual(set(data["dag"]["synthesis"]["deps"]),
                             {"planner", "research_a", "research_b"})
            self.assertTrue(trace.read_text().count('"event"') >= 4)


    def test_runs_root_creates_unique_immutable_history_and_private_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for _ in range(2):
                completed = subprocess.run([
                    sys.executable, "-m", "agentos.harness_run",
                    "examples/agent-declarations.json",
                    "--runs-root", str(root), "--port", "0", "--exit-after-run",
                ], cwd=Path(__file__).resolve().parent.parent,
                    capture_output=True, text=True, timeout=25, check=False)
                self.assertEqual(completed.returncode, 0,
                                 completed.stdout + completed.stderr)
            sessions = sorted(path for path in root.iterdir() if path.is_dir())
            self.assertEqual(len(sessions), 2)
            for session in sessions:
                self.assertEqual(stat.S_IMODE(session.stat().st_mode), 0o700)
                for file in ("manifest.json", "report.json", "trace.jsonl"):
                    path = session / file
                    self.assertTrue(path.is_file(), file)
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                metadata = json.loads((session / "manifest.json").read_text())
                self.assertEqual(metadata["run_id"], session.name)
                self.assertEqual(metadata["status"], "succeeded")
                self.assertEqual(metadata["exit_code"], 0)
                self.assertIsNotNone(metadata["finished_utc"])
                self.assertEqual(len(metadata["plan_sha256"]), 64)
                report = json.loads((session / "report.json").read_text())
                self.assertEqual(len(report["tasks"]), 4)

    def test_runs_root_rejects_explicit_artifact_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            completed = subprocess.run([
                sys.executable, "-m", "agentos.harness_run",
                "examples/demo.json", "--runs-root", temporary,
                "--report", str(Path(temporary) / "report.json"),
                "--exit-after-run",
            ], cwd=Path(__file__).resolve().parent.parent,
                capture_output=True, text=True, timeout=10)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("cannot be combined", completed.stderr)

    def test_bind_failure_preserves_existing_report_and_trace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "report.json"
            trace = root / "trace.jsonl"
            report.write_text("previous report untouched")
            trace.write_text("previous trace untouched")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen()
                busy_port = listener.getsockname()[1]
                completed = subprocess.run([
                    sys.executable, "-m", "agentos.harness_run",
                    "examples/demo.json", "--report", str(report),
                    "--trace", str(trace), "--port", str(busy_port),
                    "--exit-after-run",
                ], cwd=Path(__file__).resolve().parent.parent,
                    capture_output=True, text=True, timeout=10)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("Cannot bind", completed.stderr)
            self.assertEqual(report.read_text(), "previous report untouched")
            self.assertEqual(trace.read_text(), "previous trace untouched")

    def test_session_records_failed_task_as_failed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = root / "failing.json"
            plan.write_text(json.dumps({"tasks": [{
                "id": "bad", "argv": [sys.executable, "-c", "import sys; sys.exit(7)"]
            }]}))
            completed = subprocess.run([
                sys.executable, "-m", "agentos.harness_run", str(plan),
                "--runs-root", str(root / "runs"), "--port", "0",
                "--exit-after-run",
            ], cwd=Path(__file__).resolve().parent.parent,
                capture_output=True, text=True, timeout=15)
            self.assertEqual(completed.returncode, 1,
                             completed.stdout + completed.stderr)
            session = next((root / "runs").iterdir())
            manifest = json.loads((session / "manifest.json").read_text())
            report = json.loads((session / "report.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["exit_code"], 1)
            self.assertEqual(manifest["plan_sha256"],
                             hashlib.sha256(plan.read_bytes()).hexdigest())
            self.assertEqual(report["tasks"]["bad"]["status"], "failed")

    def test_runner_rejects_colliding_report_and_trace_paths(self):
        with tempfile.TemporaryDirectory() as dir:
            path = str(Path(dir) / "same.json")
            result = subprocess.run([
                sys.executable, "-m", "agentos.harness_run",
                "examples/demo.json", "--report", path, "--trace", path,
                "--exit-after-run",
            ], cwd=Path(__file__).resolve().parent.parent,
                capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 2)
            self.assertIn("must be different", result.stderr)
