"""Incremental, read-only index of a single append-only Supervisor JSONL trace.

The trace remains the source of truth. The sparse byte-offset index is rebuilt
in memory on server restart or file rotation; it does not rewrite, truncate,
renumber or claim to resume any native agent. All visible records must form a
single contiguous sequence from zero. A partial last line is not yet evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path

from .record_stream import (MAX_CURSOR, MAX_WINDOW, CursorConflict, CursorError)

STRIDE = 128
MAX_RECORD_BYTES = 1024 * 1024
_SESSION = re.compile(r"^[0-9a-f]{32}$")


def _no_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = item
    return value


def _reject_non_json_constant(value):
    raise ValueError("non-JSON numeric constant")


def _decode_record(line: bytes) -> dict:
    try:
        event = json.loads(line, object_pairs_hook=_no_duplicate_keys,
                           parse_constant=_reject_non_json_constant)
    except (ValueError, UnicodeError) as exc:
        raise CursorConflict("malformed complete JSONL record") from exc
    if not isinstance(event, dict):
        raise CursorConflict("trace record must be a JSON object")
    if "seq" not in event or "session_id" not in event:
        raise CursorConflict("legacy or unsequenced trace record")
    if (not isinstance(event.get("event"), str) or
            type(event.get("time_ns")) is not int or
            type(event.get("agent_path")) is not list or
            not all(isinstance(item, str) for item in event["agent_path"])):
        raise CursorConflict("trace record missing required supervisor fact fields")
    return event


class TraceIndex:
    def __init__(self, path: Path | None):
        self.path = Path(path) if path is not None else None
        self._lock = threading.Lock()
        self._reset()

    def _reset(self) -> None:
        self._identity: tuple[int, int] | None = None
        self._size = 0
        self._mtime_ns = 0
        self._ctime_ns = 0
        self._scan_pos = 0
        self._head_guard = b""
        self._tail_guard = b""
        self._last_seq = -1
        self._session: str | None = None
        self._checkpoints: list[int] = []

    @staticmethod
    def _guard(file, pos: int) -> bytes:
        """Hash known prefix and most recently verified bytes to detect rewrites."""
        h = hashlib.blake2s(digest_size=16)
        saved = file.tell()
        file.seek(0)
        h.update(file.read(min(128, pos)))
        file.seek(max(0, pos - 128))
        h.update(file.read(min(128, pos)))
        file.seek(saved)
        return h.digest()

    def _load_append(self, file, info) -> None:
        identity = (info.st_dev, info.st_ino)
        changed = (
            self._identity is not None and (
                self._identity != identity or info.st_size < self._scan_pos or
                (info.st_size == self._size and
                 (info.st_mtime_ns != self._mtime_ns or info.st_ctime_ns != self._ctime_ns)) or
                (self._scan_pos > 0 and
                 self._guard(file, self._scan_pos) != self._head_guard)
            )
        )
        if changed:
            self._reset()
        self._identity = identity
        self._size = info.st_size
        self._mtime_ns = info.st_mtime_ns
        self._ctime_ns = info.st_ctime_ns

        file.seek(self._scan_pos)
        while file.tell() < info.st_size:
            start = file.tell()
            # Never parse bytes appended after the observed file size.
            remaining = info.st_size - start
            line = file.readline(min(MAX_RECORD_BYTES + 1, remaining))
            if not line.endswith(b"\n"):
                if len(line) > MAX_RECORD_BYTES:
                    raise CursorConflict("oversized record in trace")
                # Incomplete final append: retry it on the next read.
                break
            if len(line) > MAX_RECORD_BYTES:
                raise CursorConflict("oversized record in trace")
            event = _decode_record(line)
            seq = event.get("seq")
            sid = event.get("session_id")
            if (type(seq) is not int or not 0 <= seq <= MAX_CURSOR or
                    not isinstance(sid, str) or not _SESSION.fullmatch(sid)):
                raise CursorConflict("legacy, invalid or unsequenced trace record")
            if seq != self._last_seq + 1:
                raise CursorConflict("missing, reordered or truncated trace records")
            if self._session is None:
                self._session = sid
            if sid != self._session:
                raise CursorConflict("trace contains multiple execution sessions")
            if seq % STRIDE == 0:
                self._checkpoints.append(start)
            self._last_seq = seq
            self._scan_pos = file.tell()
        if self._scan_pos:
            self._head_guard = self._guard(file, self._scan_pos)

    def read(self, *, after: int = -1, limit: int = 100,
             session_id: str | None = None) -> dict:
        """Read a verified page, with O(STRIDE+limit) record decoding after indexing.

        Index construction scans all complete events once per server/file
        generation and scans only new appended lines on subsequent requests.
        """
        if after < -1 or after > MAX_CURSOR or not 1 <= limit <= MAX_WINDOW:
            raise CursorError("invalid cursor")
        if after >= 0 and session_id is None:
            raise CursorError("session_id is required for incremental cursor")
        with self._lock:
            if self.path is None:
                return self._empty(after, session_id)
            try:
                file = self.path.open("rb")
            except FileNotFoundError:
                self._reset()
                return self._empty(after, session_id)
            with file:
                info = os.fstat(file.fileno())
                self._load_append(file, info)
                if self._session is None:
                    return self._empty(after, session_id)
                if session_id is not None and session_id != self._session:
                    raise CursorConflict("session identity changed")
                if after > self._last_seq:
                    raise CursorConflict("cursor ahead of observed last record")
                start_seq = after + 1
                selected: list[dict] = []
                if start_seq <= self._last_seq:
                    checkpoint = start_seq // STRIDE
                    file.seek(self._checkpoints[checkpoint])
                    expected = checkpoint * STRIDE
                    while expected <= self._last_seq and len(selected) < limit:
                        line = file.readline(MAX_RECORD_BYTES + 1)
                        # Re-check even after indexing: changing the file while
                        # serving a page must never silently return wrong facts.
                        item = _decode_record(line)
                        if (item.get("seq") != expected or
                                item.get("session_id") != self._session):
                            raise CursorConflict("trace changed during indexed replay")
                        if expected >= start_seq:
                            selected.append(item)
                        expected += 1
                next_seq = selected[-1]["seq"] if selected else after
                return {"schema": 1, "session_id": self._session,
                        "records": selected, "next_seq": next_seq,
                        "has_more": next_seq < self._last_seq}

    @staticmethod
    def _empty(after: int, session_id: str | None) -> dict:
        if after >= 0 or session_id is not None:
            raise CursorConflict("record evidence unavailable for supplied cursor")
        return {"schema": 1, "session_id": None,
                "records": [], "next_seq": -1, "has_more": False}
