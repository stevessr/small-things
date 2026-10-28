"""Validated AgentOS execution contract and lifecycle."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]{0,63}$")


class Status(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class AgentSpec:
    id: str
    argv: tuple[str, ...]
    deps: tuple[str, ...] = ()
    tenant: str = "default"
    kind: str = "process"
    cpu_units: int = 1
    memory_mib: int = 256
    timeout_s: float = 30.0
    retries: int = 0
    priority: int = 0

    @classmethod
    def parse(cls, raw: dict) -> "AgentSpec":
        if not isinstance(raw, dict):
            raise ValueError("task must be an object")
        allowed = set(cls.__dataclass_fields__)
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"unknown task fields: {sorted(unknown)}")
        argv = raw.get("argv")
        deps = raw.get("deps", [])
        if not isinstance(argv, (list, tuple)) or not argv or not all(isinstance(x, str) and x and "\x00" not in x for x in argv):
            raise ValueError("argv must be a nonempty array of command arguments")
        if not isinstance(deps, (list, tuple)) or not all(isinstance(x, str) for x in deps) or len(set(deps)) != len(deps):
            raise ValueError("deps must be unique task IDs")
        values = dict(raw, argv=tuple(argv), deps=tuple(deps))
        try:
            spec = cls(**values)
        except TypeError as exc:
            raise ValueError(str(exc)) from exc
        if not _NAME.fullmatch(spec.id) or not _NAME.fullmatch(spec.tenant):
            raise ValueError("id and tenant must be simple names (1-64 characters)")
        if any(not _NAME.fullmatch(dep) or dep == spec.id for dep in spec.deps):
            raise ValueError("invalid or self-referential dependency")
        if spec.kind not in {"process", "model", "tool"}:
            raise ValueError("kind must be process, model or tool")
        for key, value, low, high in (
            ("cpu_units", spec.cpu_units, 1, 256),
            ("memory_mib", spec.memory_mib, 32, 1048576),
            ("retries", spec.retries, 0, 5),
            ("priority", spec.priority, -100, 100),
        ):
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key} must be an integer in [{low}, {high}]")
        if type(spec.timeout_s) not in (int, float) or not 0 < spec.timeout_s <= 86400:
            raise ValueError("timeout_s must be within (0, 86400]")
        return spec


@dataclass
class AgentResult:
    id: str
    status: Status = Status.PENDING
    attempts: int = 0
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    elapsed_s: float = 0.0
    isolation: str = "unknown"
    resource_metrics: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {**vars(self), "status": self.status.value}


@dataclass(frozen=True)
class Budget:
    cpu_units: int = 2
    memory_mib: int = 1024
    max_tasks: int = 128

    @classmethod
    def parse(cls, raw: dict) -> "Budget":
        if not isinstance(raw, dict) or set(raw) - set(cls.__dataclass_fields__):
            raise ValueError("invalid budget")
        try:
            budget = cls(**raw)
        except TypeError as exc:
            raise ValueError(str(exc)) from exc
        for value in (budget.cpu_units, budget.memory_mib, budget.max_tasks):
            if type(value) is not int or value <= 0:
                raise ValueError("budget dimensions must be positive integers")
        if budget.max_tasks > 10000:
            raise ValueError("max_tasks exceeds safety limit")
        return budget
