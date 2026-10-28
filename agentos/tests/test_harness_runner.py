"""End-to-end CLI Harness Runner: real jobs, trace, report and live HTTP bootstrap."""
from __future__ import annotations

import json
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
