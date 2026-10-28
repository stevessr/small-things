"""Event-driven Linux inotify changes for the read-only Harness UI.

The watcher observes the parent directories of the known report/trace files,
including atomic rename into place. It emits no periodic data polls. The
Condition notifies connected SSE readers only when relevant files change.
"""
from __future__ import annotations

import ctypes
import os
import select
import struct
import sys
import threading
from pathlib import Path

IN_CLOSE_WRITE = 0x00000008
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_ATTRIB = 0x00000004
FLAGS = IN_CLOSE_WRITE | IN_MOVED_TO | IN_CREATE | IN_DELETE | IN_ATTRIB


class ChangeWatch:
    def __init__(self, paths: list[Path]):
        self.paths = {str(p.absolute()) for p in paths}
        self.condition = threading.Condition()
        self.version = 0
        self._stopped = threading.Event()
        self._fd: int | None = None
        self._thread: threading.Thread | None = None
        if not self.paths or sys.platform != "linux":
            return
        libc = ctypes.CDLL(None, use_errno=True)
        try:
            fd = libc.inotify_init1(os.O_CLOEXEC | os.O_NONBLOCK)
            if fd < 0:
                return
            dirs = sorted({str(Path(p).parent) for p in self.paths})
            watch_names: dict[int, str] = {}
            for parent in dirs:
                if not Path(parent).is_dir():
                    continue
                wd = libc.inotify_add_watch(fd, os.fsencode(parent), FLAGS)
                if wd >= 0:
                    watch_names[wd] = parent
            if not watch_names:
                os.close(fd)
                return
            self._fd = fd
            self._thread = threading.Thread(target=self._listen, args=(watch_names,), daemon=True,
                                            name="agentos-inotify")
            self._thread.start()
        except (OSError, AttributeError):
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None

    @property
    def active(self) -> bool:
        return self._fd is not None and not self._stopped.is_set()

    def _listen(self, directories: dict[int, str]) -> None:
        assert self._fd is not None
        while not self._stopped.is_set():
            try:
                ready, _, _ = select.select([self._fd], [], [], 0.5)
                if not ready:
                    continue
                data = os.read(self._fd, 65536)
            except (OSError, ValueError):
                break
            offset = 0
            while offset + 16 <= len(data):
                wd, mask, _, length = struct.unpack_from("iIII", data, offset)
                offset += 16
                if offset + length > len(data):
                    break
                name = os.fsdecode(data[offset:offset + length].split(b"\0", 1)[0])
                offset += length
                parent = directories.get(wd)
                if (mask & FLAGS and parent and
                        str(Path(parent) / name) in self.paths):
                    self.signal()
        # If inotify exits unexpectedly, disconnect SSE subscribers instead of
        # silently emitting heartbeats forever with stale task state.
        self._stopped.set()
        with self.condition:
            self.condition.notify_all()

    def signal(self) -> None:
        with self.condition:
            self.version += 1
            self.condition.notify_all()

    def wait(self, last: int, timeout: float = 20.0) -> int:
        with self.condition:
            self.condition.wait_for(lambda: self.version > last or self._stopped.is_set(),
                                    timeout=timeout)
            return self.version

    def close(self) -> None:
        self._stopped.set()
        self.signal()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
