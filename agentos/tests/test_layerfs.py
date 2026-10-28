"""Bridge contract tests (stub SDK). NOT live LayerFS/Docker/FUSE tests."""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from agentos.layerfs import LayerFSClient, LayerFSFailure, LayerFSRuntime
from agentos.models import AgentSpec, Budget, Status

FAKE_MODULE = Path(__file__).with_name("fake_layerfs.mjs").resolve()


@unittest.skipUnless(shutil.which("node"), "Node.js required for mocked LayerFS bridge tests")
class LayerFSBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env_patch = patch.dict(os.environ, {
            "LAYERFS_PROJECT": "agentos-test",
            "LAYERFS_AGENT_MODULE": str(FAKE_MODULE),
        })
        self.env_patch.start()

    async def asyncTearDown(self):
        self.env_patch.stop()

    async def test_init_project_l0(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            result = await LayerFSClient().initialize(root, timeout_ms=5000)
        self.assertEqual(result["kind"], "Initialized")
        self.assertEqual(result["project"], "agentos-test")

    async def test_fc_selective_restore_is_new_branch_and_atomic(self):
        result = await LayerFSClient().fc_restore(
            "working", "checkpoint", ["/a.txt", "/gone.txt"])
        self.assertEqual(result["based_on"], "working")
        self.assertNotEqual(result["branch"], "working")
        self.assertEqual(result["changes"], 2)
        self.assertTrue(result["result"]["safe"])
        self.assertEqual(result["result"]["changes"], [
            {"op": "write", "path": "/a.txt", "content": "before\n"},
            {"op": "rm", "path": "/gone.txt"},
        ])
        self.assertNotIn("/keep.txt", str(result["result"]["changes"]))

    async def test_fc_rejects_path_escape(self):
        with self.assertRaisesRegex(LayerFSFailure, "invalid absolute file path"):
            await LayerFSClient().fc_restore("working", "checkpoint", ["/../etc/passwd"])

    async def test_fc_rejects_duplicate_path(self):
        with self.assertRaisesRegex(LayerFSFailure, "duplicate FC"):
            await LayerFSClient().fc_restore("working", "checkpoint", ["/a.txt", "/a.txt"])

    async def test_branch_exec_returns_a_committed_layerfs_ref(self):
        runtime = LayerFSRuntime([
            AgentSpec.parse({"id": "one", "argv": ["printf", "%s", "safe; echo bad"]}),
            AgentSpec.parse({"id": "two", "deps": ["one"],
                             "argv": ["true"]}),
        ], Budget(cpu_units=1, memory_mib=1024))
        result = await runtime.run()
        self.assertEqual(result["one"].status, Status.SUCCEEDED)
        self.assertEqual(result["two"].status, Status.SUCCEEDED)
        self.assertTrue(result["one"].filesystem_branch.startswith("ag-one-"))
        self.assertEqual(result["two"].filesystem_commit, "c1")
        self.assertIn("timeout --signal", result["one"].stdout)
        self.assertIn("'safe; echo bad'", result["one"].stdout)

    async def test_failed_sandbox_exec_blocks_dependent(self):
        with patch.dict(os.environ, {"LAYERFS_FAKE_EXIT": "7"}):
            runtime = LayerFSRuntime([
                AgentSpec.parse({"id": "failed", "argv": ["false"]}),
                AgentSpec.parse({"id": "blocked", "deps": ["failed"], "argv": ["true"]}),
            ])
            result = await runtime.run()
        self.assertEqual(result["failed"].status, Status.FAILED)
        self.assertEqual(result["blocked"].status, Status.BLOCKED)
        self.assertEqual(result["failed"].filesystem_branch, "")

    async def test_missing_module_fails_without_silent_host_fallback(self):
        with patch.dict(os.environ, {"LAYERFS_AGENT_MODULE": "/no/such/agent.mjs"}):
            with self.assertRaises(LayerFSFailure):
                await LayerFSClient().fc_restore("working", "checkpoint", ["/a.txt"])


if __name__ == "__main__":
    unittest.main()
