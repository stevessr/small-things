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


class LinuxTelemetryTests(unittest.TestCase):
    def test_cgroup_stat_snapshot_parser(self):
        from agentos.linux import CgroupV2
        with tempfile.TemporaryDirectory() as tmp:
            cg = Path(tmp)
            (cg / "memory.peak").write_text("2048\n")
            (cg / "cpu.stat").write_text("usage_usec 135\nuser_usec 100\n")
            (cg / "memory.events").write_text("oom 1\noom_kill 0\n")
            stats = CgroupV2.snapshot(cg)
            self.assertEqual(stats["memory_peak"], 2048)
            self.assertEqual(stats["cpu_stat"]["usage_usec"], 135)
            self.assertEqual(stats["memory_events"]["oom"], 1)


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

    async def test_transitive_dependency_failure_closure(self):
        # Do not depend on set iteration order to propagate BLOCKED through DAG.
        tasks = [task("root", "import sys; sys.exit(2)")]
        tasks += [task(f"step{i}", "pass", deps=[("root" if i == 0
                                               else f"step{i - 1}")])
                  for i in range(12)]
        tasks.append(task("independent", "print('ok')"))
        runtime = AgentRuntime(tasks)
        result = await runtime.run()
        self.assertEqual(result["root"].status, Status.FAILED)
        self.assertTrue(all(result[f"step{i}"].status == Status.BLOCKED
                            for i in range(12)))
        self.assertEqual(result["independent"].status, Status.SUCCEEDED)

    async def test_invalid_graph_is_rejected(self):
        with self.assertRaises(ValueError):
            AgentRuntime([task("a", deps=["b"]), task("b", deps=["a"])])
        with self.assertRaises(ValueError):
            AgentRuntime([task("a", cpu_units=3)], Budget(cpu_units=2))

    async def test_agent_declares_batch_with_sibling_dependencies(self):
        plan = """from agentos.client import declare_tasks
import sys
def child(id, deps=[]):
    return {"id": id, "deps": deps,
            "argv": [sys.executable, "-c", "print('declared child')"],
            "memory_mib": 128}
print(declare_tasks([
    child("fetch_a"), child("fetch_b"),
    child("combine", ["fetch_a", "fetch_b"])
]))
"""
        engine = AgentRuntime([task("planner", plan)])
        result = await engine.run()
        self.assertEqual(set(result), {"planner", "fetch_a", "fetch_b", "combine"})
        self.assertTrue(all(x.status == Status.SUCCEEDED for x in result.values()))
        self.assertEqual(set(engine.tasks["combine"].deps),
                         {"planner", "fetch_a", "fetch_b"})
        started = {ev["task"]: ev["time_ns"] for ev in engine.events
                   if ev["event"] == "started"}
        finished = {ev["task"]: ev["time_ns"] for ev in engine.events
                    if ev["event"] == "finished"}
        self.assertGreater(started["combine"], finished["fetch_a"])
        self.assertGreater(started["combine"], finished["fetch_b"])
        self.assertEqual(engine.report()["declared_by"]["combine"], "planner")

    async def test_atomic_batch_rejects_cycle_without_partial_admission(self):
        engine = AgentRuntime([task("root")])
        engine._started = True
        before = set(engine.tasks)
        with self.assertRaisesRegex(ValueError, "cycle"):
            await engine._declare_tasks("root", [
                {"id": "a", "deps": ["b"], "argv": ["true"]},
                {"id": "b", "deps": ["a"], "argv": ["true"]},
            ])
        self.assertEqual(set(engine.tasks), before)
        self.assertEqual(set(engine.pending), before)
        engine.context.close()
        engine._temp.cleanup()

    async def test_atomic_batch_rejects_unknown_cross_tenant_duplicate_and_quota(self):
        engine = AgentRuntime([task("root", tenant="tenantA"),
                               task("other", tenant="tenantB")],
                              Budget(cpu_units=2, memory_mib=512, max_tasks=3))
        engine._started = True
        specs = [
            [{"id": "a", "deps": ["unknown"], "argv": ["true"]}],
            [{"id": "a", "deps": ["other"], "argv": ["true"]}],
            [{"id": "a", "tenant": "tenantB", "argv": ["true"]}],
            [{"id": "a", "argv": ["true"]}, {"id": "b", "argv": ["true"]}],
            [{"id": "a", "argv": ["true"]}, {"id": "a", "argv": ["true"]}],
        ]
        for batch in specs:
            with self.assertRaises((ValueError, PermissionError)):
                await engine._declare_tasks("root", batch)
            self.assertEqual(set(engine.tasks), {"root", "other"})
            self.assertEqual(set(engine.pending), {"root", "other"})
        engine.context.close()
        engine._temp.cleanup()

    async def test_declaration_invalid_is_not_retried_and_blocks_downstream(self):
        plan = """from agentos.client import request
request("declare_tasks", tasks=[
    {"id": "declared", "deps": ["no-such-dependency"], "argv": ["true"]}
])"""
        engine = AgentRuntime([task("planner", plan, retries=2),
                               task("unrelated", "print('ok')")])
        result = await engine.run()
        self.assertEqual(result["planner"].status, Status.FAILED)
        self.assertEqual(result["unrelated"].status, Status.SUCCEEDED)
        self.assertNotIn("declared", result)


if __name__ == "__main__":
    unittest.main()
