"""OAR-inspired ordered supervisor-fact cursor, NOT native harness replay.

The source of truth is the append-only AgentOS JSONL trace. This module never
synthesizes missing records or infers success from silence. Replay only reads
observed supervisor events, and cannot resume a running process/model turn.
"""
from __future__ import annotations

import re

MAX_WINDOW = 200
MAX_CURSOR = 10**12
_SESSION = re.compile(r"^[0-9a-f]{32}$")


class CursorError(ValueError):
    """Invalid cursor or missing evidence; caller should not skip a gap."""


class CursorConflict(CursorError):
    """Prior history has been rotated, truncated, or contains gaps."""


def parse_cursor(query: dict[str, list[str]]) -> tuple[int, int, str | None]:
    """Require caller-supplied session identity after the initial read."""
    if set(query) - {"after", "limit", "session_id"}:
        raise CursorError("unknown record cursor fields")
    if any(len(values) != 1 for values in query.values()):
        raise CursorError("cursor fields must appear only once")
    raw_after = query.get("after", ["-1"])[0]
    raw_limit = query.get("limit", ["100"])[0]
    # Explicit lexical limits prevent pathological huge integer conversion.
    if len(raw_after) > 13 or not re.fullmatch(r"(?:-1|[0-9]+)", raw_after):
        raise CursorError("after must be -1 or a nonnegative integer")
    if len(raw_limit) > 3 or not re.fullmatch(r"[0-9]+", raw_limit):
        raise CursorError("limit must be a positive decimal integer")
    after, limit = int(raw_after), int(raw_limit)
    if after > MAX_CURSOR or not 1 <= limit <= MAX_WINDOW:
        raise CursorError("cursor or limit exceeds maximum")
    expected_session = query.get("session_id", [None])[0]
    if expected_session is not None and not _SESSION.fullmatch(expected_session):
        raise CursorError("session_id must be a 32-character lowercase hex ID")
    if after >= 0 and expected_session is None:
        raise CursorError("session_id is required after the initial read")
    return after, limit, expected_session


def replay_window(records: list[dict], *, after: int = -1, limit: int = 100,
                  session_id: str | None = None) -> dict:
    """Return a contiguous bounded slice with a verifiable next cursor.

    A truncated prefix, unsequenced legacy trace, missing event, unexpected
    session, or future cursor is a conflict (HTTP 409), never fake data.
    """
    if after < -1 or after > MAX_CURSOR or not 1 <= limit <= MAX_WINDOW:
        raise CursorError("invalid record window")
    if after >= 0 and session_id is None:
        raise CursorError("session_id required for an incremental cursor")
    if not records:
        if session_id is not None or after >= 0:
            raise CursorConflict("record evidence unavailable for supplied cursor")
        return {"schema": 1, "session_id": None, "records": [],
                "next_seq": -1, "has_more": False}
    first_seq = records[0].get("seq")
    observed_session = records[0].get("session_id")
    if type(first_seq) is not int or first_seq < 0 or (
            not isinstance(observed_session, str) or
            not _SESSION.fullmatch(observed_session)):
        raise CursorConflict("legacy or unsequenced trace; cursor replay unavailable")
    if session_id is not None and session_id != observed_session:
        raise CursorConflict("session identity changed; refuse cross-run replay")
    prev = first_seq - 1
    for record in records:
        seq = record.get("seq")
        if (type(seq) is not int or seq != prev + 1 or
                record.get("session_id") != observed_session):
            raise CursorConflict("missing, reordered or cross-session record in window")
        prev = seq
    if after < first_seq - 1:
        raise CursorConflict(f"earliest available seq is {first_seq}; cursor gap")
    if after > prev:
        raise CursorConflict(f"cursor {after} is ahead of observed last seq {prev}")
    # Only verified contiguous records are handed to observers.
    offset = max(0, after - first_seq + 1)
    selected = records[offset:offset + limit]
    next_seq = selected[-1]["seq"] if selected else after
    return {"schema": 1, "session_id": observed_session,
            "records": selected, "next_seq": next_seq,
            "has_more": next_seq < prev}
