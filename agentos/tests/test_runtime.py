from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

from agentos import AgentRuntime, AgentSpec, Budget, Status
from agentos.context import ContextStore


def task(task_id, source="pass", **kwargs):
    return AgentSpec.parse({"id": task_id, "argv": [sys.executable, "-c", source], **kwargs})


class ContextTests(unittest.TestCase):
    def test_compression_reuse_and_tenant_isolation(self):
        db = ContextStore()
        try:
            outcome = db.put("alice", "shared", "repeated text " * 500)
            self.assertEqual(outcome["codec"], "zlib")
            self.assertLess(outcome["stored_bytes"], outcome["raw_bytes"])
            self.assertEqual(db.get("alice", "shared"), "repeated text " * 500)
            self.assertIsNone(db.get("bob", "shared"))
            self.assertEqual(db.stats()["hits"], 1)
            self.assertEqual(db.stats()["misses"], 1)
        finally:
            db.close()

    def test_reject_large_context(self):
        db = ContextStore()
        try:
            with self.assertRaises(ValueError):
                db.put("a", "b", "x" * 70000)
        finally:
            db.close()


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_dependency_execution_and_bus(self):
        producer = task("producer",
            "from agentos.client import request; "
            "request('context_put',key='k',value='abc'*1000); "
            "request('send',to='consumer',payload={'value':42})")
        consumer = task("consumer",
            "from agentos.client import request; "
            "assert request('context_get',key='k')['value']=='abc'*1000; "
            "assert request('recv')['messages'][0]['payload']['value']==42",
            deps=["producer"])
        runtime = AgentRuntime([consumer, producer])
        result = await runtime.run()
        self.assertEqual({k: v.status for k, v in result.items()},
                         {"producer": Status.SUCCEEDED, "consumer": Status.SUCCEEDED})
        self.assertGreater(runtime.report()["context"]["hits"], 0)

    async def test_dynamic_task_creation(self):
        script = ("import sys; from agentos.client import request; "
                  "request('spawn',task={'id':'child','argv':[sys.executable,'-c','print(123)'],"
                  "'memory_mib':128})")
        runtime = AgentRuntime([task("parent", script)], Budget(cpu_units=1, memory_mib=512))
        result = await runtime.run()
        self.assertEqual(set(result), {"parent", "child"})
        self.assertTrue(all(x.status == Status.SUCCEEDED for x in result.values()))
        self.assertEqual(runtime.tasks["child"].deps, ("parent",))

    async def test_failure_propagation_without_cascade(self):
        runtime = AgentRuntime([
            task("bad", "import sys; sys.exit(7)", retries=1),
            task("dependent", "pass", deps=["bad"]),
            task("independent", "print('healthy')")])
        result = await runtime.run()
        self.assertEqual(result["bad"].status, Status.FAILED)
        self.assertEqual(result["bad"].attempts, 2)
        self.assertEqual(result["dependent"].status, Status.BLOCKED)
        self.assertEqual(result["independent"].status, Status.SUCCEEDED)

    async def test_wall_timeout(self):
        runtime = AgentRuntime([task("slow", "import time; time.sleep(3)", timeout_s=0.15),
                                task("fast", "print('ok')")])
        result = await runtime.run()
        self.assertEqual(result["slow"].status, Status.FAILED)
        self.assertIn("timeout", result["slow"].error)
        self.assertEqual(result["fast"].status, Status.SUCCEEDED)

    async def test_resource_budget_serialization(self):
        runtime = AgentRuntime([task("a", "import time; time.sleep(.08)", cpu_units=1),
                                task("b", "import time; time.sleep(.08)", cpu_units=1)],
                               Budget(cpu_units=1, memory_mib=512))
        result = await runtime.run()
        self.assertTrue(all(x.status == Status.SUCCEEDED for x in result.values()))
        lifecycle = [(x["event"], x.get("task")) for x in runtime.events
                     if x["event"] in ("started", "finished")]
        self.assertEqual(lifecycle, [("started", "a"), ("finished", "a"),
                                     ("started", "b"), ("finished", "b")])

    async def test_cross_tenant_ipc_is_denied(self):
        attacker = task("attacker",
            "from agentos.client import request; "
            "request('send',to='victim',payload='bad')", tenant="tenantA")
        victim = task("victim", "pass", tenant="tenantB")
        runtime = AgentRuntime([attacker, victim])
        result = await runtime.run()
        self.assertEqual(result["attacker"].status, Status.FAILED)
        self.assertEqual(result["victim"].status, Status.SUCCEEDED)

    async def test_invalid_graph_is_rejected(self):
        with self.assertRaises(ValueError):
            AgentRuntime([task("a", deps=["b"]), task("b", deps=["a"])])
        with self.assertRaises(ValueError):
            AgentRuntime([task("a", cpu_units=3)], Budget(cpu_units=2))


if __name__ == "__main__":
    unittest.main()
