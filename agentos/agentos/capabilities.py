"""Explicit AgentOS backend capability declarations, inspired by OAR.

A declared capability is not an account probe, a successful SDK install, or
an executed workload. Conditional capabilities need external evidence; callers
must not silently treat them as supported.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    status: str
    detail: str
    evidence: str


FEATURES: dict[str, dict[str, Capability]] = {
    "host": {
        "dag": Capability("supported", "Validated DAG and resource reservations", "AgentRuntime + tests/test_runtime.py"),
        "dynamic_declare": Capability("supported", "Atomic Host IPC task declarations", "AgentBus + tests/test_runtime.py"),
        "unix_ipc": Capability("supported", "Local per-agent capability token, logical tenant isolation", "agentos/bus.py"),
        "cgroup_v2": Capability("conditional", "Requires delegated writable cgroup v2 controllers", "doctor + --require-cgroup; real delegation is not part of CI"),
        "layerfs_fc": Capability("unsupported", "Host subprocess mode has no LayerFS checkpoints", "agentos/layerfs.py"),
        "record_replay": Capability("supported", "Bounded recorded supervisor facts, with explicit gap errors", "agentos/record_stream.py"),
        "native_resume": Capability("unsupported", "No persisted process/model turn can be continued after crash", "docs/run-sessions.md"),
        "native_agent_protocol": Capability("unsupported", "No direct Claude/Codex/OAR session protocol adapter", "docs/oar-comparison.md"),
        "gpu_kv_cache": Capability("unsupported", "SQLite text context is not model KV cache", "docs/capabilities.md"),
    },
    "layerfs": {
        "dag": Capability("supported", "Shared DAG admission and logical reservations", "AgentRuntime + LayerFSRuntime"),
        "dynamic_declare": Capability("conditional", "Validated manifest path; requires real SDK/Docker/FUSE integration", "Fake SDK CI only"),
        "unix_ipc": Capability("unsupported", "Host Unix IPC is not projected to Docker", "agentos/layerfs.py"),
        "cgroup_v2": Capability("unsupported", "AgentOS reservations do not enforce Docker cgroup limits", "agentos/layerfs.py"),
        "layerfs_fc": Capability("conditional", "History/rewind/files implemented; requires real LayerFS SDK Store and daemon", "Fake SDK CI only"),
        "record_replay": Capability("supported", "Supervisor trace replay only; not native tool/model replay", "agentos/record_stream.py"),
        "native_resume": Capability("unsupported", "Non-destructive FC file fork is not a suspended process resume", "docs/layerfs-fc.md"),
        "native_agent_protocol": Capability("unsupported", "No direct coding-agent protocol session adapter", "docs/oar-comparison.md"),
        "gpu_kv_cache": Capability("unsupported", "No GPU cache-sharing implementation", "docs/capabilities.md"),
    },
}


class UnsupportedCapability(ValueError):
    def __init__(self, backend: str, feature: str, state: str):
        self.backend, self.feature, self.state = backend, feature, state
        self.code = "unsupported" if state == "unsupported" else "evidence_required"
        super().__init__(f"{backend}.{feature}: {self.code} ({state})")


def describe(backend: str) -> dict:
    if backend not in FEATURES:
        raise ValueError("unknown backend")
    return {"schema": 1, "backend": backend,
            "features": {key: vars(value).copy()
                         for key, value in sorted(FEATURES[backend].items())}}


def require(backend: str, feature: str) -> None:
    if backend not in FEATURES or feature not in FEATURES[backend]:
        raise UnsupportedCapability(backend, feature, "unsupported")
    state = FEATURES[backend][feature].status
    if state != "supported":
        raise UnsupportedCapability(backend, feature, state)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Declare AgentOS capabilities without starting processes or probing accounts")
    parser.add_argument("--backend", choices=sorted(FEATURES), default="host")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()
    data = describe(args.backend)
    if args.format == "json":
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        for name, entry in data["features"].items():
            print(f"{name:24s} {entry['status']:12s} {entry['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
