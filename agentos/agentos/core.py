"""Resource-aware DAG execution and subprocess lifecycle supervisor."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import uuid
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
        # Runtime execution identity, NOT a native model conversation ID.
        self.session_id = uuid.uuid4().hex
        self._next_seq = 0
        self.trace_path = trace_path
        self.context = ContextStore(context_path)
        self.cgroups = CgroupV2(cgroup_root, required=require_cgroup)
        self._temp = tempfile.TemporaryDirectory(prefix="agentos-")
        self.bus = AgentBus(Path(self._temp.name) / "bus.sock",
                            self.context, self.tasks.get, self._spawn, self._declare_tasks)
        self._started = False
        self.declared_by: dict[str, str] = {}
        for task in tasks:
            self.add(task, initial=True)
        self._validate_graph()

    def _event(self, name: str, **fields) -> None:
        """Append one observed supervisor fact, with ordered attribution.

        Time is observational only; seq is authoritative ordering. The
        lineage covers dynamically declared parents. Do not synthesize
        missing worker-native events or claim this is a native conversation.
        """
        task = fields.get("task")
        agent_path: list[str] = []
        if isinstance(task, str):
            seen = {task}
            ancestor = self.declared_by.get(task)
            while ancestor is not None and ancestor not in seen:
                seen.add(ancestor)
                agent_path.append(ancestor)
                ancestor = self.declared_by.get(ancestor)
            agent_path.reverse()
        event = {"seq": self._next_seq, "session_id": self.session_id,
                 "agent_path": agent_path, "time_ns": time.time_ns(),
                 "event": name, **fields}
        self._next_seq += 1
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
        self._event("admitted", task=task.id, tenant=task.tenant, kind=task.kind,
                    deps=list(task.deps), priority=task.priority,
                    cpu_units=task.cpu_units, memory_mib=task.memory_mib)

    def _validate_graph(self, tasks: dict[str, AgentSpec] | None = None) -> None:
        """Validate DAG in O(V+E), without recursive call-stack exhaustion."""
        tasks = self.tasks if tasks is None else tasks
        indegree = {key: 0 for key in tasks}
        dependents: dict[str, list[str]] = {key: [] for key in tasks}
        for key, spec in tasks.items():
            for dep in spec.deps:
                if dep not in tasks:
                    raise ValueError(f"unknown dependency: {dep}")
                if tasks[dep].tenant != spec.tenant:
                    raise ValueError("cross-tenant dependency denied")
                indegree[key] += 1
                dependents[dep].append(key)
        ready = [key for key, degree in indegree.items() if degree == 0]
        visited = 0
        while ready:
            key = ready.pop()
            visited += 1
            for child in dependents[key]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if visited != len(tasks):
            raise ValueError("dependency cycle detected")

    async def _spawn(self, parent: str, raw: dict) -> str:
        # Backward-compatible single-task declaration.
        result = await self._declare_tasks(parent, [raw])
        return result[0]

    async def _declare_tasks(self, parent: str, raw_tasks: list[dict]) -> list[str]:
        """Atomically admit one batch with explicit intra-batch DAG edges.

        Every declared task depends on its declaring parent (which is currently
        RUNNING or completing); other dependencies may reference existing tasks
        or siblings within this same batch. No unresolved forward references
        beyond this batch are accepted.
        """
        if not self._started or parent not in self.tasks:
            raise ValueError("declaration requires an existing running Agent")
        if not isinstance(raw_tasks, list) or not 1 <= len(raw_tasks) <= 32:
            raise ValueError("declare_tasks accepts 1–32 task objects")
        if len(self.tasks) + len(raw_tasks) > self.budget.max_tasks:
            raise ValueError("declared tasks exceed max_tasks")
        owner = self.tasks[parent]
        batch: dict[str, AgentSpec] = {}
        for raw in raw_tasks:
            if not isinstance(raw, dict):
                raise ValueError("declared task must be an object")
            if "tenant" in raw and raw["tenant"] != owner.tenant:
                raise PermissionError("cannot declare tasks in another tenant")
            deps = raw.get("deps", [])
            if not isinstance(deps, (tuple, list)):
                raise ValueError("deps must be an array")
            if len(deps) > 128:
                raise ValueError("too many declared dependencies")
            # Parent is always an enforced barrier, even if omitted by Agent.
            merged = list(deps)
            if parent not in merged:
                merged.append(parent)
            spec = AgentSpec.parse({**raw, "tenant": owner.tenant, "deps": merged})
            if spec.id in batch or spec.id in self.tasks:
                raise ValueError(f"duplicate task ID: {spec.id}")
            if spec.cpu_units > self.budget.cpu_units or spec.memory_mib > self.budget.memory_mib:
                raise ValueError(f"task {spec.id} exceeds cluster resource budget")
            batch[spec.id] = spec
        candidate = {**self.tasks, **batch}
        self._validate_graph(candidate)
        # All validation precedes mutation, so a rejected batch admits nothing.
        for task in batch.values():
            self.tasks[task.id] = task
            self.pending.add(task.id)
            self.declared_by[task.id] = parent
            self._event("declared", task=task.id, parent=parent,
                        tenant=task.tenant, deps=list(task.deps))
            self._event("admitted", task=task.id, tenant=task.tenant, kind=task.kind,
                    deps=list(task.deps), priority=task.priority,
                    cpu_units=task.cpu_units, memory_mib=task.memory_mib)
        return list(batch)

    async def _after_success(self, spec: AgentSpec, result: AgentResult) -> None:
        """Backend hook after a successful attempt and before scheduler completion."""
        return None

    async def _attempt(self, spec: AgentSpec, token: str) -> tuple[int | None, str, str, str, dict]:
        group = None
        proc = None
        metrics: dict = {}
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
            return proc.returncode, stdout, stderr, "", metrics
        except asyncio.TimeoutError:
            return None, "", "", f"wall timeout ({spec.timeout_s}s)", metrics
        except (OSError, ValueError, RuntimeError) as exc:
            return None, "", "", f"{type(exc).__name__}: {exc}", metrics
        finally:
            if proc is not None:
                # Also kill abandoned children after a nominal parent exit.
                terminate_group(proc.pid)
                if proc.returncode is None:
                    await proc.wait()
            metrics.update(self.cgroups.snapshot(group))
            self.cgroups.release(group)

    async def _execute(self, spec: AgentSpec) -> AgentResult:
        result = AgentResult(id=spec.id, status=Status.RUNNING, isolation=self.cgroups.mode)
        started = time.monotonic()
        self._event("started", task=spec.id, cpu_units=spec.cpu_units, memory_mib=spec.memory_mib)
        token = self.bus.register(spec)
        try:
            for number in range(spec.retries + 1):
                result.attempts += 1
                code, out, err, reason, metrics = await self._attempt(spec, token)
                result.resource_metrics = metrics
                result.exit_code = code
                result.stdout, result.stderr = out, err
                result.error = reason or (f"exit code {code}" if code != 0 else "")
                if code == 0 and not reason:
                    try:
                        await self._after_success(spec, result)
                    except (ValueError, PermissionError) as exc:
                        # Malformed declarations cannot publish successful
                        # downstream tasks; do not re-run side-effectful calls.
                        result.error = "task declaration rejected: " + str(exc)
                        self._event("declaration_rejected", task=spec.id, error=str(exc))
                        break
                    result.status = Status.SUCCEEDED
                    break
                if metrics.get("layerfs_unknown"):
                    break  # uncertain Workspace outcome: never silently replay
                if number < spec.retries:
                    self._event("retry", task=spec.id, attempt=number + 1, error=result.error)
                    await asyncio.sleep(min(1.0, 0.05 * 2 ** number))
            if result.status != Status.SUCCEEDED:
                result.status = Status.FAILED
        finally:
            self.bus.unregister(token)
            result.elapsed_s = round(time.monotonic() - started, 6)
            self._event("finished", task=spec.id, status=result.status.value,
                        attempts=result.attempts, elapsed_s=result.elapsed_s,
                        error=result.error, resource_metrics=result.resource_metrics)
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
                # Transitive failure closure: one failed node may block an
                # arbitrarily long DAG even when no other task is running.
                # Recompute to a fixpoint BEFORE declaring the queue stalled.
                while True:
                    blocked = [
                        key for key in sorted(self.pending)
                        if any(self.results.get(dep) and self.results[dep].status in
                               (Status.FAILED, Status.BLOCKED)
                               for dep in self.tasks[key].deps)
                    ]
                    if not blocked:
                        break
                    for key in blocked:
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
        return {"session_id": self.session_id, "last_seq": self._next_seq - 1,
                "budget": vars(self.budget), "isolation": self.cgroups.mode,
                "tasks": {key: result.as_dict() for key, result in sorted(self.results.items())},
                "dag": {key: {"deps": list(spec.deps), "kind": spec.kind,
                              "tenant": spec.tenant, "priority": spec.priority,
                              "cpu_units": spec.cpu_units, "memory_mib": spec.memory_mib}
                        for key, spec in sorted(self.tasks.items())},
                "context": self.context.stats(), "declared_by": self.declared_by,
                "events": self.events}
