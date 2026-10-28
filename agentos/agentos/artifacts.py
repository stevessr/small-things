"""Durable, private run artifacts. All paths are selected locally by operator."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_text(path: Path, content: str) -> None:
    """Write with 0600 permissions and atomic replacement, including fsync."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        # Best-effort directory fsync for rename durability.
        if os.name == "posix":
            try:
                directory = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            except OSError:
                # Not every volume/overlay supports fsync on a directory.
                # The atomic rename already completed successfully.
                pass
    finally:
        Path(name).unlink(missing_ok=True)


def atomic_json(path: Path, value: dict) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def init_trace(path: Path, events: list[dict]) -> None:
    """Rotate a selected trace using an atomic initial snapshot, mode 0600."""
    atomic_text(path, "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events))


def create_run_dir(root: Path) -> Path:
    """Create a never-before-used private (0700) run directory."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    prefix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
    return Path(tempfile.mkdtemp(prefix=prefix, dir=root))
