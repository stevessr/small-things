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
from agentos.sessions import inspect_run, list_runs


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
                self.assertRegex(metadata["session_id"], r"^[a-f0-9]{32}$")
                self.assertGreaterEqual(metadata["last_seq"], 0)
                self.assertEqual(metadata["exit_code"], 0)
                self.assertIsNotNone(metadata["finished_utc"])
                self.assertEqual(len(metadata["plan_sha256"]), 64)
                self.assertEqual(len(metadata["report_sha256"]), 64)
                self.assertEqual(len(metadata["trace_sha256"]), 64)
                schema = json.loads((Path(__file__).resolve().parent.parent /
                                     "docs" / "session-manifest.schema.json").read_text())
                self.assertEqual(set(metadata), set(schema["properties"]))
                self.assertTrue(set(schema["required"]).issubset(metadata))
                self.assertEqual(inspect_run(session)["integrity"], "ok")
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

    def test_session_verifier_rejects_gap_even_with_valid_sha256(self):
        from agentos.artifacts import file_sha256

        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary) / "20261028T000000Z-evidence"
            session.mkdir()
            session_id = "c" * 32
            report = session / "report.json"
            trace = session / "trace.jsonl"
            report.write_text(json.dumps({
                "tasks": {}, "session_id": session_id, "last_seq": 2
            }))
            trace.write_text(
                json.dumps({"seq": 0, "session_id": session_id,
                            "event": "started", "time_ns": 1,
                            "agent_path": [], "task": "a"}) + "\n" +
                json.dumps({"seq": 2, "session_id": session_id,
                            "event": "finished", "time_ns": 2,
                            "agent_path": [], "task": "a"}) + "\n"
            )
            (session / "manifest.json").write_text(json.dumps({
                "schema": 1, "run_id": session.name, "status": "succeeded",
                "exit_code": 0, "started_utc": "2026-10-28T00:00:00+00:00",
                "finished_utc": "2026-10-28T00:01:00+00:00",
                "filesystem": "host", "plan_sha256": "a" * 64,
                "task_count_initial": 1, "report": "report.json", "trace": "trace.jsonl",
                "session_id": session_id, "last_seq": 2,
                "report_sha256": file_sha256(report), "trace_sha256": file_sha256(trace),
            }))
            integrity = inspect_run(session)
            self.assertEqual(integrity["integrity"], "invalid")
            self.assertTrue(any("missing" in error or "sequence" in error
                                for error in integrity["errors"]))

            # Recompute the checksum to show that syntactically unfinished
            # evidence cannot be certified by matching digests alone.
            trace.write_text("".join(json.dumps({
                "seq": seq, "session_id": session_id, "event": "admitted",
                "time_ns": seq + 1, "agent_path": [], "task": "a"
            }) + "\n" for seq in range(3)))
            with trace.open("a") as stream:
                stream.write('{"seq":3,"session_id":')
            manifest_path = session / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["trace_sha256"] = file_sha256(trace)
            manifest_path.write_text(json.dumps(manifest))
            integrity = inspect_run(session)
            self.assertEqual(integrity["integrity"], "invalid")
            self.assertIn("incomplete trailing", " ".join(integrity["errors"]))

    def test_running_session_is_incomplete_not_invalid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "20261028T000000Z-abcd1234"
            run.mkdir()
            (run / "manifest.json").write_text(json.dumps({
                "schema": 1, "run_id": run.name, "status": "running",
                "exit_code": None, "started_utc": "2026-10-28T00:00:00+00:00",
                "finished_utc": None, "filesystem": "host",
                "plan_sha256": "0" * 64, "task_count_initial": 1,
                "report": "report.json", "trace": "trace.jsonl"
            }))
            result = inspect_run(run)
            self.assertEqual(result["integrity"], "incomplete")
            self.assertEqual(result["errors"], [])

    def test_run_history_cli_and_integrity_detect_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            completed = subprocess.run([
                sys.executable, "-m", "agentos.harness_run",
                "examples/demo.json", "--runs-root", str(root),
                "--port", "0", "--exit-after-run"
            ], cwd=Path(__file__).resolve().parent.parent,
                capture_output=True, text=True, timeout=20)
            self.assertEqual(completed.returncode, 0,
                             completed.stdout + completed.stderr)
            self.assertEqual(len(list_runs(root)), 1)
            session = next(root.iterdir())
            verified = subprocess.run([
                sys.executable, "-m", "agentos.sessions", "verify",
                "--session", str(session), "--format", "json"
            ], cwd=Path(__file__).resolve().parent.parent,
                capture_output=True, text=True, timeout=10)
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertEqual(json.loads(verified.stdout)["integrity"], "ok")
            listed = subprocess.run([
                sys.executable, "-m", "agentos.sessions", "list",
                "--root", str(root), "--format", "json"
            ], cwd=Path(__file__).resolve().parent.parent,
                capture_output=True, text=True, timeout=10)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertEqual(json.loads(listed.stdout)[0]["run_id"], session.name)
            with (session / "trace.jsonl").open("a") as stream:
                stream.write('{"event":"fake"}\n')
            self.assertEqual(inspect_run(session)["integrity"], "invalid")
            verified = subprocess.run([
                sys.executable, "-m", "agentos.sessions", "verify",
                "--session", str(session)
            ], cwd=Path(__file__).resolve().parent.parent,
                capture_output=True, text=True, timeout=10)
            self.assertEqual(verified.returncode, 2)
            self.assertIn("checksum mismatch", verified.stdout)

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
