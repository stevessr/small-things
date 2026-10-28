"""Full-history sparse-index replay, rotation, append and corruption tests."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from agentos.harness_ui import MAX_TRACE, read_trace, start_server
from agentos.record_index import STRIDE, MAX_RECORD_BYTES, TraceIndex
from agentos.record_stream import CursorConflict

SID = "1" * 32
NEXT_SID = "2" * 32


def event(seq: int, sid: str = SID, **extra):
    return {"seq": seq, "session_id": sid, "agent_path": [],
            "time_ns": 1_000_000 + seq, "event": "admitted",
            "task": "worker", **extra}


def append(path: Path, *events: dict):
    with path.open("a", encoding="utf-8") as stream:
        for value in events:
            stream.write(json.dumps(value, separators=(",", ":")) + "\n")


class IndexedReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "trace.jsonl"
        self.index = TraceIndex(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_trace_and_append_from_partial_line(self):
        self.assertEqual(self.index.read()["session_id"], None)
        first = json.dumps(event(0))
        with self.path.open("wb") as stream:
            stream.write(first[:len(first)//2].encode())
        self.assertEqual(self.index.read()["records"], [])
        with self.path.open("ab") as stream:
            stream.write(first[len(first)//2:].encode() + b"\n")
        self.assertEqual(self.index.read()["next_seq"], 0)
        with self.path.open("a") as stream:
            stream.write(json.dumps(event(1))[:-1])
        self.assertEqual(self.index.read(after=0, session_id=SID)["records"], [])
        with self.path.open("a") as stream:
            stream.write("}\n")
        replay = self.index.read(after=0, session_id=SID)
        self.assertEqual([e["seq"] for e in replay["records"]], [1])

    def test_sparse_checkpoints_cover_more_than_tail_and_4000_events(self):
        # This deliberately exceeds both the dashboard 2 MiB tail and 4000
        # event ceiling. The record endpoint must not discard old evidence.
        with self.path.open("w", encoding="utf-8") as stream:
            for seq in range(12_000):
                stream.write(json.dumps(event(seq, padding="x" * 120)) + "\n")
        self.assertGreater(self.path.stat().st_size, MAX_TRACE)
        self.assertLessEqual(len(read_trace(self.path)), 4000)
        first = self.index.read(limit=3)
        self.assertEqual([r["seq"] for r in first["records"]], [0, 1, 2])
        assert first["session_id"] == SID
        tail = self.index.read(after=11_900, session_id=SID, limit=200)
        self.assertEqual(tail["records"][0]["seq"], 11901)
        self.assertEqual(tail["records"][-1]["seq"], 11999)
        self.assertFalse(tail["has_more"])
        self.assertEqual(len(self.index._checkpoints), (12000 + STRIDE - 1)//STRIDE)
        self.assertEqual(self.index.read(after=11999, session_id=SID)["records"], [])
        append(self.path, event(12000))
        latest = self.index.read(after=11999, session_id=SID)
        self.assertEqual([r["seq"] for r in latest["records"]], [12000])

    def test_complete_corruption_and_missing_sequence_fail_closed(self):
        append(self.path, event(0), event(1), event(3))
        with self.assertRaisesRegex(CursorConflict, "missing"):
            self.index.read()
        with self.assertRaises(CursorConflict):
            self.index.read(after=0, session_id=SID)

    def test_legacy_or_broken_json_and_oversized_record_rejected(self):
        self.path.write_text('{"event":"admitted","task":"worker"}\n')
        with self.assertRaisesRegex(CursorConflict, "legacy"):
            self.index.read()
        self.path.write_text('{"seq":0, invalid}\n')
        with self.assertRaisesRegex(CursorConflict, "malformed"):
            self.index.read()
        self.path.write_text(json.dumps(event(0, payload="a" * MAX_RECORD_BYTES)) + "\n")
        with self.assertRaisesRegex(CursorConflict, "oversized"):
            self.index.read()

    def test_ambiguous_json_and_missing_fact_fields_are_rejected(self):
        cases = [
            '{"seq":0,"seq":0,"session_id":"' + SID + '","event":"admitted","time_ns":1,"agent_path":[]}\n',
            '{"seq":0,"session_id":"' + SID + '","event":"admitted","time_ns":NaN,"agent_path":[]}\n',
            '{"seq":0,"session_id":"' + SID + '","event":"admitted","time_ns":1,"agent_path":null}\n',
            '{"seq":0,"session_id":"' + SID + '","event":"admitted","time_ns":1}\n',
        ]
        for raw in cases:
            with self.subTest(raw=raw[:50]):
                self.path.write_text(raw)
                with self.assertRaises(CursorConflict):
                    self.index.read()

    def test_rotation_and_same_size_rewrite_never_mix_sessions(self):
        append(self.path, event(0), event(1))
        self.assertEqual(self.index.read()["session_id"], SID)
        replacement = self.path.with_suffix(".tmp")
        append(replacement, event(0, NEXT_SID))
        replacement.replace(self.path)
        with self.assertRaisesRegex(CursorConflict, "session identity"):
            self.index.read(after=1, session_id=SID)
        self.assertEqual(self.index.read()["session_id"], NEXT_SID)
        old = self.path.read_text()
        # In-place rewrite with identical byte length; guards must notice.
        rewritten = old.replace(NEXT_SID, SID)
        self.assertEqual(len(rewritten), len(old))
        self.path.write_text(rewritten)
        self.assertEqual(self.index.read()["session_id"], SID)

    def test_truncated_prefix_cannot_be_relabelled(self):
        append(self.path, event(2), event(3))
        with self.assertRaisesRegex(CursorConflict, "missing"):
            self.index.read()

    def test_concurrent_clients_use_a_coherent_index(self):
        from concurrent.futures import ThreadPoolExecutor
        with self.path.open("w") as stream:
            for seq in range(512):
                stream.write(json.dumps(event(seq)) + "\n")
        def one(n):
            return self.index.read(after=n-1, session_id=SID if n else None, limit=1)["records"][0]["seq"]
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(list(pool.map(one, range(512))), list(range(512)))

    def test_new_server_rebuilds_index_from_original_trace(self):
        append(self.path, *(event(n) for n in range(340)))
        rebuilt = TraceIndex(self.path)
        self.assertEqual(rebuilt.read(after=128, session_id=SID)["records"][0]["seq"], 129)


class IndexedHttpTests(unittest.TestCase):
    def test_http_replay_reads_first_record_of_large_trace(self):
        with tempfile.TemporaryDirectory() as temporary:
            trace = Path(temporary) / "trace.jsonl"
            with trace.open("w") as stream:
                for n in range(9000):
                    stream.write(json.dumps(event(n, padding="x" * 180)) + "\n")
            server = start_server(None, trace, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(url + "/api/records?limit=1", timeout=15) as response:
                    first = json.load(response)
                self.assertEqual([r["seq"] for r in first["records"]], [0])
                with urlopen(url + "/api/records?after=8998&limit=10&session_id=" + SID,
                             timeout=15) as response:
                    end = json.load(response)
                self.assertEqual([r["seq"] for r in end["records"]], [8999])
                self.assertFalse(end["has_more"])
                trace.write_text(json.dumps(event(0, NEXT_SID)) + "\n")
                with self.assertRaises(HTTPError) as problem:
                    urlopen(url + "/api/records?after=0&session_id=" + SID)
                self.assertEqual(problem.exception.code, 409)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
