"""Real LayerFS v1.1.0 SDK bridge and isolated per-Agent Workspace backend.

This backend never runs task argv on the AgentOS host. LayerFS starts its own
Docker sandbox. Host CPU/memory reservations DO NOT enforce sandbox cgroups.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

from .core import AgentRuntime
from .models import AgentResult, AgentSpec, Budget

_BRIDGE = Path(__file__).with_name("layerfs_bridge.mjs")
MAX_BRIDGE_REPLY = 2 * 1024 * 1024


class LayerFSFailure(RuntimeError):
    pass


class LayerFSClient:
    def __init__(self, node: str = "node", bridge: Path = _BRIDGE):
        self.node = node
        self.bridge = Path(bridge)
        if not shutil.which(node):
            raise LayerFSFailure("Node.js >=20 must be installed for LayerFS")
        if not os.environ.get("LAYERFS_PROJECT"):
            raise LayerFSFailure("LAYERFS_PROJECT must name an initialized LayerFS project")

    async def call(self, payload: dict, timeout_s: float = 120.0) -> dict:
        proc = await asyncio.create_subprocess_exec(
            self.node, str(self.bridge), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        data = json.dumps(payload, ensure_ascii=False).encode()
        if len(data) > 128 * 1024:
            proc.kill()
            await proc.wait()
            raise LayerFSFailure("bridge request too large")
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(data), timeout_s)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise LayerFSFailure(
                "LayerFS bridge timeout: sandbox command or cleanup state may be unknown; "
                "inspect LayerFS sandbox records before retrying") from exc
        if len(stdout) > MAX_BRIDGE_REPLY:
            raise LayerFSFailure("oversized bridge response")
        try:
            response = json.loads(stdout)
        except (ValueError, UnicodeDecodeError) as exc:
            raise LayerFSFailure("invalid LayerFS bridge JSON: " + stderr.decode(
                errors="replace")[:500]) from exc
        if not response.get("ok"):
            raise LayerFSFailure(str(response.get("code", "")) + ": " +
                                 str(response.get("error", "LayerFS operation failed")))
        if proc.returncode != 0:
            raise LayerFSFailure("LayerFS bridge exited nonzero despite success output")
        return response["value"]

    async def initialize(self, source: str, timeout_ms: int = 300000) -> dict:
        """Create LayerFS L0 from the full project tree, including ignored files."""
        root = Path(source).resolve(strict=True)
        if not root.is_dir():
            raise LayerFSFailure("LayerFS Init source must be a directory")
        return await self.call({"action": "init", "source": str(root),
                                "timeout_ms": timeout_ms},
                               timeout_s=timeout_ms / 1000 + 30)

    async def fc_history(self, branch: str) -> dict:
        return await self.call({"action": "fc_history", "branch": branch})

    async def fc_rewind(self, branch: str, checkpoint: str) -> dict:
        return await self.call({"action": "fc_rewind", "branch": branch,
                                "checkpoint": checkpoint})

    async def fc_restore(self, branch: str, checkpoint: str,
                         paths: list[str]) -> dict:
        return await self.call({"action": "fc", "branch": branch,
                                "checkpoint": checkpoint, "paths": paths})


class LayerFSRuntime(AgentRuntime):
    """DAG supervisor with per-task LayerFS branches and Docker workspaces.

    In v0.2 the Unix IPC broker is NOT projected into Docker; use purely
    filesystem-based Agent tasks. Dynamic spawn/context IPC requires a later
    explicitly bridged transport.
    """

    def __init__(self, tasks: list[AgentSpec], budget: Budget | None = None,
                 *, node: str = "node", trace_path: str | None = None):
        super().__init__(tasks, budget=budget, trace_path=trace_path)
        self.layerfs = LayerFSClient(node=node)

    async def _attempt(self, spec: AgentSpec, token: str) -> tuple[int | None, str, str, str, dict]:
        # The scheduler reserves logical slots, but Docker owns actual cgroups.
        parents = [self.results[dep].filesystem_branch for dep in spec.deps]
        if any(not branch for branch in parents):
            return None, "", "", "dependency has no LayerFS branch", {}
        try:
            result = await self.layerfs.call(
                {"action": "run", "id": spec.id, "argv": list(spec.argv),
                 "parents": parents, "timeout_s": float(spec.timeout_s)},
                timeout_s=spec.timeout_s + 120)
            metrics = {"layerfs_branch": result.get("branch"),
                       "layerfs_commit": result.get("commit"),
                       "isolation": "LayerFS Docker sandbox (container quota not enforced)"}
            return (result["exit_code"], result.get("stdout", ""),
                    result.get("stderr", ""), result.get("error", ""), metrics)
        except (LayerFSFailure, OSError) as exc:
            # Unknown commit state must not be blindly replayed.
            return None, "", "", str(exc), {"layerfs_unknown": True}

    async def _execute(self, spec: AgentSpec) -> AgentResult:
        result = await super()._execute(spec)
        result.filesystem_branch = result.resource_metrics.get("layerfs_branch") or ""
        result.filesystem_commit = result.resource_metrics.get("layerfs_commit")
        result.isolation = "layerfs-docker (no AgentOS cgroup quota)"
        return result
