"""Capability honesty: conditional is not supported; opt-in requirements fail before side effects."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agentos.capabilities import FEATURES, UnsupportedCapability, describe, require

ROOT = Path(__file__).resolve().parent.parent


class CapabilityTests(unittest.TestCase):
    def test_all_backends_declare_same_explicit_feature_vocabulary(self):
        self.assertEqual(set(FEATURES), {"host", "layerfs"})
        self.assertEqual(set(FEATURES["host"]), set(FEATURES["layerfs"]))
        for backend in FEATURES:
            doc = describe(backend)
            self.assertEqual(doc["schema"], 1)
            self.assertEqual(doc["backend"], backend)
            for name, entry in doc["features"].items():
                self.assertIn(entry["status"], {"supported", "conditional", "unsupported"})
                self.assertTrue(entry["evidence"], name)
                self.assertTrue(entry["detail"], name)

    def test_supported_means_supported_only(self):
        require("host", "unix_ipc")
        require("host", "dynamic_declare")
        require("layerfs", "dag")
        for backend, feature, expected in [
            ("host", "native_resume", "unsupported"),
            ("host", "cgroup_v2", "evidence_required"),
            ("layerfs", "layerfs_fc", "evidence_required"),
            ("layerfs", "unix_ipc", "unsupported"),
            ("host", "unknown_feature", "unsupported"),
        ]:
            with self.subTest(backend=backend, feature=feature):
                with self.assertRaises(UnsupportedCapability) as error:
                    require(backend, feature)
                self.assertEqual(error.exception.code, expected)
                self.assertEqual(error.exception.feature, feature)

    def test_cli_is_no_account_probing_and_json_is_machine_readable(self):
        process = subprocess.run([
            sys.executable, "-m", "agentos.capabilities",
            "--backend", "layerfs", "--format", "json"
        ], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        data = json.loads(process.stdout)
        self.assertEqual(data["features"]["native_resume"]["status"], "unsupported")
        self.assertEqual(data["features"]["layerfs_fc"]["status"], "conditional")
        self.assertEqual(data["features"]["record_replay"]["status"], "supported")

    def test_runner_rejects_unavailable_capability_before_creating_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = root / "runs"
            command = [
                sys.executable, "-m", "agentos.harness_run",
                "examples/demo.json", "--filesystem", "layerfs",
                "--require-capability", "unix_ipc", "--runs-root", str(runs),
                "--exit-after-run", "--port", "0",
            ]
            process = subprocess.run(command, cwd=ROOT, capture_output=True,
                                     text=True, timeout=10)
            self.assertEqual(process.returncode, 2)
            self.assertIn("unsupported", process.stderr)
            self.assertFalse(runs.exists())

    def test_cli_rejects_unsupported_or_conditional_without_execution(self):
        for capability in ("native_resume", "cgroup_v2"):
            with self.subTest(capability=capability):
                process = subprocess.run([
                    sys.executable, "-m", "agentos.cli", "examples/demo.json",
                    "--require-capability", capability
                ], cwd=ROOT, capture_output=True, text=True, timeout=10)
                self.assertEqual(process.returncode, 2)
                self.assertIn(capability, process.stderr)


if __name__ == "__main__":
    unittest.main()
