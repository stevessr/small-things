"""Linux process limits and optional cgroup v2 resource enforcement."""
from __future__ import annotations

import os
import resource
import signal
from pathlib import Path

from .models import AgentSpec


def set_child_limits(memory_mib: int, timeout_s: float) -> None:
    """Executed in the child immediately before exec, under Linux."""
    memory = memory_mib * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    # RLIMIT_CPU is CPU time; wall clock is enforced independently by the supervisor.
    cpu = max(1, int(timeout_s) + 1)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))


def terminate_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


class CgroupV2:
    def __init__(self, delegated_root: str | None, required: bool = False):
        self.root: Path | None = None
        self._active: set[Path] = set()
        self.mode = "rlimit+process-group"
        if not delegated_root:
            if required:
                raise RuntimeError("cgroup enforcement requested but --cgroup-root is absent")
            return
        root = Path(delegated_root).resolve()
        if not (root / "cgroup.controllers").exists():
            if required:
                raise RuntimeError("provided root is not a cgroup v2 directory")
            return
        run_root = root / f"agentos-{os.getpid()}"
        try:
            run_root.mkdir(exist_ok=False)
        except OSError:
            if required:
                raise
            return
        self.root = run_root
        self.mode = "cgroup-v2+rlimit+process-group"

    def create(self, spec: AgentSpec) -> Path | None:
        if self.root is None:
            return None
        group = self.root / spec.id
        group.mkdir(exist_ok=False)
        try:
            (group / "memory.max").write_text(str(spec.memory_mib * 1024 * 1024))
            (group / "cpu.max").write_text(f"{spec.cpu_units * 100000} 100000")
            (group / "pids.max").write_text("64")
        except OSError:
            group.rmdir()
            raise
        self._active.add(group)
        return group

    @staticmethod
    def attach(group: Path | None, pid: int) -> None:
        if group is not None:
            (group / "cgroup.procs").write_text(str(pid))

    def release(self, group: Path | None) -> None:
        if group is None:
            return
        try:
            killer = group / "cgroup.kill"
            if killer.exists():
                killer.write_text("1")
            group.rmdir()
            self._active.discard(group)
        except OSError:
            # Retain for close() to retry; cannot hide lingering processes.
            pass

    def close(self) -> None:
        for group in list(self._active):
            self.release(group)
        if self.root:
            try:
                self.root.rmdir()
            except OSError as exc:
                raise RuntimeError(f"cgroup cleanup failed: {self.root}") from exc
