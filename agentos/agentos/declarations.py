"""Write Agent task declarations into the isolated LayerFS Workspace.

Requires AGENTOS_DECLARATIONS to be provided by the LayerFS supervisor.
Never write to an arbitrary path controlled by the caller.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def write_manifest(tasks: list[dict]) -> str:
    """Atomically write version 1 declaration manifest (max 60 KiB)."""
    target = os.environ.get("AGENTOS_DECLARATIONS")
    if not target:
        raise RuntimeError("AGENTOS_DECLARATIONS is not set (requires LayerFS task)")
    path = Path(target)
    if not path.is_absolute() or path.suffix != ".json" or path.name != (
            os.environ.get("AGENTOS_AGENT_ID", "") + ".json"):
        raise RuntimeError("invalid Agent declaration target")
    payload = json.dumps({"version": 1, "tasks": tasks}, ensure_ascii=False).encode()
    if not 0 < len(payload) <= 60 * 1024:
        raise ValueError("manifest must be 1–60 KiB")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".manifest-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return str(path)
