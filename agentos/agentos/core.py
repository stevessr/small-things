"""Resource-aware DAG execution and subprocess lifecycle supervisor."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

from .bus import AgentBus
from .context import ContextStore
from .linux import CgroupV2, set_child_limits, terminate_group
from .models import AgentResult, AgentSpec, Budget, Status

OUTPUT_LIMIT = 512 * 1024


async def _read_bounded(stream: asyncio.StreamReader) -> str:
    data = bytearray()
    while chunk := await stream.read(8192):
        data.extend(chunk)
        if len(data) > OUTPUT_LIMIT:
            raise ValueError("process output exceeds 512 KiB per stream")
    return data.decode("utf-8", errors="replace")


class AgentRuntime:
    def __init__(self, tasks: list[AgentSpec], budget: Budget | None = None,
                 context_path: str = ":memory:", cgroup_root: str | None = None,
                 require_cgroup: bool = False, trace_path: str | None = None):
        self.budget = budget or Budget()
        self.tasks: dict[str, AgentSpec] = {}
        self.pending: set[str] = set()
        self.results: dict[str, AgentResult] = {}
        self.events: list[dict] = []
        self.trace_path = trace_path
        self.context = ContextStore(context_path)
        self.cgroups = CgroupV2(cgroup_root, required=require_cgroup)
        self._temp = tempfile.TemporaryDirectory(prefix="agentos-")
        self.bus = AgentBus(Path(self._temp.name) / "bus.sock",
                            self.context, self.tasks.get, self._spawn)
        self._started = False
        for task in tasks:
            self.add(task, initial=True)
        self._validate_graph()

    def _event(self, name: str, **fields) -> None:
        event = {"time_ns": time.time_ns(), "event": name, **fields}
        self.events.append(event)
        if self.trace_path:
            path = Path(self.trace_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(event, ensure_ascii=False) + "\n")

    def add(self, task: AgentSpec, initial: bool = False) -> None:
        if task.id in self.tasks:
            raise ValueError(f"duplicate task ID: {task.id}")
        if len(self.tasks) >= self.budget.max_tasks:
            raise ValueError("max_tasks reached")
        if task.cpu_units > self.budget.cpu_units or task.memory_mib > self.budget.memory_mib:
            raise ValueError(f"task {task.id} exceeds cluster resource budget")
        if not initial:
            if not self._started:
                raise ValueError("dynamic spawn requires a running runtime")
            if any(dep not in self.tasks for dep in task.deps):
                raise ValueError("dynamic task refers to unknown dependency")
            if any(self.tasks[dep].tenant != task.tenant for dep in task.deps):
                raise ValueError("cross-tenant dependency denied")
        self.tasks[task.id] = task
        self.pending.add(task.id)
        self._event("admitted", task=task.id, tenant=task.tenant, kind=task.kind)

    def _validate_graph(self) -> None:
        visited: dict[str, int] = {}

        def visit(key: str) -> None:
            if visited.get(key) == 1:
                raise ValueError("dependency cycle detected")
            if visited.get(key) == 2:
                return
            visited[key] = 1
            for dep in self.tasks[key].deps:
                if dep not in self.tasks:
                    raise ValueError(f"unknown dependency: {dep}")
                if self.tasks[dep].tenant != self.tasks[key].tenant:
                    raise ValueError("cross-tenant dependency denied")
                visit(dep)
            visited[key] = 2

        for key in self.tasks:
            visit(key)

    async def _spawn(self, parent: str, raw: dict) -> str:
        if not isinstance(raw, dict):
            raise ValueError("spawn task must be an object")
        owner = self.tasks[parent]
        if "tenant" in raw and raw["tenant"] != owner.tenant:
            raise PermissionError("cannot spawn into another tenant")
        # Children depend on the parent for a deterministic DAG and no orphan races.
        deps = list(raw.get("deps", []))
        if parent not in deps:
            deps.append(parent)
        child = AgentSpec.parse({**raw, "tenant": owner.tenant, "deps": deps})
        self.add(child)
        return child.id

    async def _attempt(self, spec: AgentSpec, token: str) -> tuple[int | None, str, str, str]:
        group = None
        proc = None
        try:
            group = self.cgroups.create(spec)
            env = os.environ.copy()
            env.update(AGENTOS_BUS=str(self.bus.path), AGENTOS_TOKEN=token,
                       AGENTOS_AGENT_ID=spec.id, AGENTOS_TENANT=spec.tenant,
                       AGENTOS_KIND=spec.kind)
            proc = await asyncio.create_subprocess_exec(
                *spec.argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=env, start_new_session=True,
                preexec_fn=lambda: set_child_limits(spec.memory_mib, spec.timeout_s))
            self.cgroups.attach(group, proc.pid)
            stdout, stderr, _ = await asyncio.wait_for(
                asyncio.gather(_read_bounded(proc.stdout), _read_bounded(proc.stderr), proc.wait()),
                timeout=spec.timeout_s)
            return proc.returncode, stdout, stderr, ""
        except asyncio.TimeoutError:
            return None, "", "", f"wall timeout ({spec.timeout_s}s)"
        except (OSError, ValueError, RuntimeError) as exc:
            return None, "", "", f"{type(exc).__name__}: {exc}"
        finally:
            if proc is not None:
                # Also kill abandoned children after a nominal parent exit.
                terminate_group(proc.pid)
                if proc.returncode is None:
                    await proc.wait()
            self.cgroups.release(group)

    async def _execute(self, spec: AgentSpec) -> AgentResult:
        result = AgentResult(id=spec.id, status=Status.RUNNING, isolation=self.cgroups.mode)
        started = time.monotonic()
        self._event("started", task=spec.id, cpu_units=spec.cpu_units, memory_mib=spec.memory_mib)
        token = self.bus.register(spec)
        try:
            for number in range(spec.retries + 1):
                result.attempts += 1
                code, out, err, reason = await self._attempt(spec, token)
                result.exit_code = code
                result.stdout, result.stderr = out, err
                result.error = reason or (f"exit code {code}" if code != 0 else "")
                if code == 0 and not reason:
                    result.status = Status.SUCCEEDED
                    break
                if number < spec.retries:
                    self._event("retry", task=spec.id, attempt=number + 1, error=result.error)
                    await asyncio.sleep(min(1.0, 0.05 * 2 ** number))
            else:
                result.status = Status.FAILED
        finally:
            self.bus.unregister(token)
            result.elapsed_s = round(time.monotonic() - started, 6)
            self._event("finished", task=spec.id, status=result.status.value,
                        attempts=result.attempts, elapsed_s=result.elapsed_s,
                        error=result.error)
        return result

    async def run(self) -> dict[str, AgentResult]:
        if self._started:
            raise RuntimeError("runtime is single-use")
        self._started = True
        running: dict[asyncio.Task, AgentSpec] = {}
        reserved_cpu = reserved_mem = 0
        try:
            await self.bus.start()
            while self.pending or running:
                # Fail closed when a dependency fails; unaffected branches continue.
                for key in list(self.pending):
                    if any(self.results.get(dep) and self.results[dep].status in
                           (Status.FAILED, Status.BLOCKED) for dep in self.tasks[key].deps):
                        self.pending.remove(key)
                        self.results[key] = AgentResult(id=key, status=Status.BLOCKED,
                                                        error="dependency failed")
                        self._event("blocked", task=key)
                for key in sorted(self.pending, key=lambda k: (-self.tasks[k].priority, k)):
                    spec = self.tasks[key]
                    if not all(dep in self.results and self.results[dep].status == Status.SUCCEEDED
                               for dep in spec.deps):
                        continue
                    if reserved_cpu + spec.cpu_units > self.budget.cpu_units or (
                            reserved_mem + spec.memory_mib > self.budget.memory_mib):
                        continue
                    self.pending.remove(key)
                    reserved_cpu += spec.cpu_units
                    reserved_mem += spec.memory_mib
                    running[asyncio.create_task(self._execute(spec))] = spec
                if running:
                    done, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
                    for future in done:
                        spec = running.pop(future)
                        reserved_cpu -= spec.cpu_units
                        reserved_mem -= spec.memory_mib
                        self.results[spec.id] = future.result()
                elif self.pending:
                    raise RuntimeError("no schedulable tasks; invalid dependency state")
            return self.results
        finally:
            for future, spec in running.items():
                future.cancel()
            if running:
                await asyncio.gather(*running.keys(), return_exceptions=True)
            await self.bus.stop()
            self.cgroups.close()
            self.context.close()
            self._temp.cleanup()

    def report(self) -> dict:
        return {"budget": vars(self.budget), "isolation": self.cgroups.mode,
                "tasks": {key: result.as_dict() for key, result in sorted(self.results.items())},
                "context": self.context.stats(), "events": self.events}
