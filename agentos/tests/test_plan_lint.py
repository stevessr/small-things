"""Static contracts, operator CLI, and side-effect-free diagnostics."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentos.doctor import inspect_environment
from agentos.plan_lint import read_plan, validate_plan

ROOT = Path(__file__).resolve().parent.parent


def spec(identifier, deps=None, **extra):
    return {"id": identifier, "argv": ["python3", "-c", "print('ok')"],
            "memory_mib": 128, "deps": deps or [], **extra}


class PlanLintTests(unittest.TestCase):
    def test_all_repository_examples_have_valid_topological_dag(self):
        for example in (ROOT / "examples").glob("*.json"):
            if example.name == "harness-ui-sample.json":
                continue  # This is a report snapshot, not an execution plan.
            with self.subTest(example=example.name):
                tasks, budget, order = read_plan(example)
                self.assertEqual(set(order), {task.id for task in tasks})
                self.assertLessEqual(len(order), budget.max_tasks)
                locations = {task_id: i for i, task_id in enumerate(order)}
                for task in tasks:
                    for dep in task.deps:
                        self.assertLess(locations[dep], locations[task.id])

    def test_forward_dependency_and_shared_parents(self):
        tasks, _, order = validate_plan({"tasks": [
            spec("synthesis", ["left", "right"]), spec("left"), spec("right")
        ]})
        self.assertEqual(order[-1], "synthesis")
        self.assertEqual({t.id for t in tasks}, {"left", "right", "synthesis"})

    def test_plan_errors_reject_invalid_shapes_and_unknown_keys(self):
        invalid = [
            None, [], {}, {"tasks": []}, {"tasks": "string"},
            {"tasks": [spec("a")], "surprise": 123},
            {"tasks": [spec("a"), spec("a")]},
            {"tasks": [spec("a", ["missing"])]},
            {"tasks": [spec("a", ["b"]), spec("b", ["a"])]},
            {"tasks": [spec("a", ["b"], tenant="one"),
                       spec("b", tenant="two")]},
            {"tasks": [spec("a", cpu_units=3)], "budget": {"cpu_units": 2}},
            {"tasks": [spec("a"), spec("b")], "budget": {"max_tasks": 1}},
            {"tasks": [spec("a", memory_mib=4096)],
             "budget": {"memory_mib": 512}},
        ]
        for number, raw in enumerate(invalid):
            with self.subTest(index=number), self.assertRaises(ValueError):
                validate_plan(raw)

    def test_large_dag_lint_is_nonrecursive(self):
        raw = {"budget": {"max_tasks": 2000}, "tasks": [
            spec("node0")] + [
            spec(f"node{i}", [f"node{i - 1}"]) for i in range(1, 1500)
        ]}
        tasks, _, order = validate_plan(raw)
        self.assertEqual(len(tasks), 1500)
        self.assertEqual(order[0], "node0")
        self.assertEqual(order[-1], "node1499")

    def test_cli_accepts_json_and_never_executes_agents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.json"
            target = Path(directory) / "not-created"
            plan = {"tasks": [
                {"id": "dummy", "argv": [sys.executable, "-c",
                 f"open({str(target)!r}, 'w').write('bad')"]}
            ]}
            path.write_text(json.dumps(plan))
            process = subprocess.run([
                sys.executable, "-m", "agentos.plan_lint",
                str(path), "--format", "json"
            ], cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout)["topological_order"], ["dummy"])
            self.assertFalse(target.exists())

    def test_cli_invalid_plan_exits_2(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "invalid.json"
            plan.write_text('{"tasks": [{"id": "test", "argv": ["true"], "deps": ["x"]}]}')
            process = subprocess.run(
                [sys.executable, "-m", "agentos.plan_lint", str(plan)],
                cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 2)
            self.assertIn("PLAN INVALID", process.stderr)


class DoctorTests(unittest.TestCase):
    def test_host_check_is_read_only_and_structure_is_stable(self):
        checks = inspect_environment("host", "web")
        self.assertIn("python", {check["name"] for check in checks})
        self.assertIn("dashboard_assets", {check["name"] for check in checks})
        self.assertTrue(all(set(check) == {"name", "status", "detail"} for check in checks))
        self.assertTrue(all(check["status"] in {"ok", "warn", "fail"} for check in checks))

    def test_layerfs_missing_prerequisites_are_reported(self):
        with patch.dict("os.environ", {"LAYERFS_PROJECT": ""}):
            with patch("agentos.doctor.shutil.which", return_value=None):
                checks = inspect_environment("layerfs", "web")
        report = {entry["name"]: entry["status"] for entry in checks}
        self.assertEqual(report["layerfs_project"], "fail")
        self.assertEqual(report["node"], "fail")
        self.assertEqual(report["docker"], "fail")
        self.assertEqual(report["layerfs_runtime"], "warn")

    def test_graphical_ui_checks_display_and_cargo(self):
        with patch.dict("os.environ", {"WAYLAND_DISPLAY": "", "DISPLAY": ""}):
            with patch("agentos.doctor.shutil.which", return_value=None):
                checks = inspect_environment("host", "gpui")
        report = {entry["name"]: entry["status"] for entry in checks}
        self.assertEqual(report["graphical_session"], "warn")
        self.assertEqual(report["cargo"], "fail")

    def test_invalid_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            inspect_environment("fake", "web")
        with self.assertRaises(ValueError):
            inspect_environment("host", "fake")

    def test_doctor_json_cli_exits_success_on_host(self):
        process = subprocess.run(
            [sys.executable, "-m", "agentos.doctor", "--format", "json"],
            cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual(report["backend"], "host")
        self.assertIsInstance(report["checks"], list)


if __name__ == "__main__":
    unittest.main()
