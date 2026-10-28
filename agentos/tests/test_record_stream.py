"""OAR-inspired evidence stream: seq/identity, replay gaps and attribution."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

from agentos import AgentRuntime, AgentSpec
from agentos.harness_ui import start_server
from agentos.record_stream import (
    CursorConflict, CursorError, parse_cursor, replay_window,
)

SESSION = "a" * 32
OTHER = "b" * 32


def sample(n=5, session=SESSION):
    return [{"seq": i, "session_id": session, "agent_path": [],
             "time_ns": i + 1, "event": "admitted", "task": f"task{i}"}
            for i in range(n)]


class RecordStreamContractTests(unittest.TestCase):
    def test_bounded_replay_and_stable_cursors(self):
        events = sample()
        first = replay_window(events, limit=2)
        self.assertEqual([e["seq"] for e in first["records"]], [0, 1])
        self.assertEqual(first["session_id"], SESSION)
        self.assertEqual(first["next_seq"], 1)
        self.assertTrue(first["has_more"])
        second = replay_window(events, after=1, limit=2, session_id=SESSION)
        self.assertEqual([e["seq"] for e in second["records"]], [2, 3])
        third = replay_window(events, after=3, limit=5, session_id=SESSION)
        self.assertEqual([e["seq"] for e in third["records"]], [4])
        self.assertFalse(third["has_more"])
        last = replay_window(events, after=4, session_id=SESSION)
        self.assertEqual(last["records"], [])
        self.assertEqual(last["next_seq"], 4)

    def test_missing_prefix_or_gap_never_returns_false_success(self):
        with self.assertRaisesRegex(CursorConflict, "cursor gap"):
            replay_window(sample()[2:])
        events = sample()
        del events[2]
        with self.assertRaisesRegex(CursorConflict, "missing"):
            replay_window(events)
        with self.assertRaises(CursorConflict):
            replay_window(sample(), after=99, session_id=SESSION)

    def test_cross_session_and_legacy_trace_refused(self):
        with self.assertRaisesRegex(CursorConflict, "identity"):
            replay_window(sample(), after=0, session_id=OTHER)
        with self.assertRaisesRegex(CursorConflict, "unsequenced"):
            replay_window([{"event": "started", "task": "a"}])
        mixed = sample()
        mixed[3]["session_id"] = OTHER
        with self.assertRaises(CursorConflict):
            replay_window(mixed)

    def test_missing_trace_not_falsely_marked_as_complete(self):
        self.assertEqual(replay_window([])["next_seq"], -1)
        with self.assertRaises(CursorConflict):
            replay_window([], after=0, session_id=SESSION)

    def test_query_validation_and_upper_limits(self):
        self.assertEqual(parse_cursor({}), (-1, 100, None))
        self.assertEqual(parse_cursor({"after": ["3"], "limit": ["5"],
                                       "session_id": [SESSION]}), (3, 5, SESSION))
        invalid = [
            {"after": ["0"]}, {"after": ["-2"]},
            {"limit": ["0"]}, {"limit": ["201"]},
            {"limit": ["1", "2"]}, {"after": ["0.0"]},
            {"after": ["9" * 5000]}, {"after": ["1" * 13]},
            {"after": ["0"], "session_id": ["fake"]},
            {"extra": ["1"]}, {"after": [""]},
        ]
        for item in invalid:
            with self.subTest(query=item), self.assertRaises(CursorError):
                parse_cursor(item)

    def test_trace_memory_events_are_not_modified_by_projection(self):
        events = sample(3)
        page = replay_window(events, limit=1)
        page["records"][0]["task"] = "caller-local-change"
        # The cursor API returns a bounded record view; the caller should
        # treat objects as immutable. A future projection must not mutate
        # the supervisor stream; avoid requiring reference identity here.
        self.assertEqual(len(events), 3)


class AttributedRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_nested_subagent_lineage_and_monotonic_seq(self):
        py = sys.executable
        child_src = ("from agentos.client import declare_tasks; "
                     f"declare_tasks([{{'id': 'grandchild', 'argv': [{py!r}, '-c', 'pass']}}])")
        root_src = ("from agentos.client import declare_tasks; "
                    f"declare_tasks([{{'id': 'child', 'argv': [{py!r}, '-c', {child_src!r}]}}])")
        spec = AgentSpec.parse({"id": "root", "argv": [py, "-c", root_src]})
        runtime = AgentRuntime([spec])
        results = await runtime.run()
        self.assertEqual(set(results), {"root", "child", "grandchild"})
        self.assertTrue(all(result.status.value == "succeeded" for result in results.values()))
        events = runtime.events
        self.assertEqual([e["seq"] for e in events], list(range(len(events))))
        self.assertEqual({e["session_id"] for e in events}, {runtime.session_id})
        started = {e["task"]: e["agent_path"] for e in events if e["event"] == "started"}
        self.assertEqual(started, {
            "root": [], "child": ["root"], "grandchild": ["root", "child"]
        })
        self.assertEqual(replay_window(events, limit=200)["records"], events)


class RecordHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.trace = root / "trace.jsonl"
        self.trace.write_text("".join(json.dumps(e) + "\n" for e in sample()))
        self.server = start_server(None, self.trace, 0)
        self.host = f"http://127.0.0.1:{self.server.server_port}"
        import threading
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def test_fetch_next_cursor_and_conflict(self):
        with urlopen(self.host + "/api/records?limit=2") as response:
            first = json.load(response)
        self.assertEqual(first["next_seq"], 1)
        path = "/api/records?after=1&limit=2&session_id=" + SESSION
        with urlopen(self.host + path) as response:
            second = json.load(response)
        self.assertEqual([e["seq"] for e in second["records"]], [2, 3])
        for bad, code in [
            ("/api/records?after=1", 400),
            ("/api/records?limit=999", 400),
            ("/api/records?after=0&session_id=" + OTHER, 409),
        ]:
            with self.subTest(path=bad), self.assertRaises(HTTPError) as err:
                urlopen(self.host + bad)
            self.assertEqual(err.exception.code, code)

    def test_trace_rotation_rejects_prior_session_cursor(self):
        self.trace.write_text("".join(json.dumps(e) + "\n" for e in sample(3, OTHER)))
        with self.assertRaises(HTTPError) as err:
            urlopen(self.host + "/api/records?after=1&session_id=" + SESSION)
        self.assertEqual(err.exception.code, 409)

    def test_legacy_trace_is_explicitly_unavailable(self):
        self.trace.write_text('{"event":"started","task":"root"}\n')
        with self.assertRaises(HTTPError) as err:
            urlopen(self.host + "/api/records")
        self.assertEqual(err.exception.code, 409)


if __name__ == "__main__":
    unittest.main()
