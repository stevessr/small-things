"""Static, side-effect-free AgentOS plan audit and CLI.

Unlike the execution supervisor, this preflight does not open IPC sockets,
start Agent processes, initialize LayerFS, or create cgroups.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .models import AgentSpec, Budget


def validate_plan(raw: Any) -> tuple[list[AgentSpec], Budget, list[str]]:
    """Validate top-level contract, task IDs, cross-tenant DAG and reservations.

    Return (specs, budget, topological_order), with deterministic ordering.
    """
    if not isinstance(raw, dict):
        raise ValueError("plan root must be a JSON object")
    unknown = set(raw) - {"budget", "tasks"}
    if unknown:
        raise ValueError(f"unknown plan fields: {sorted(unknown)}")
    if "tasks" not in raw or not isinstance(raw["tasks"], list) or not raw["tasks"]:
        raise ValueError("tasks must be a nonempty array")
    budget = Budget.parse(raw.get("budget", {}))
    if len(raw["tasks"]) > budget.max_tasks:
        raise ValueError("number of initial tasks exceeds max_tasks")
    specs = [AgentSpec.parse(item) for item in raw["tasks"]]
    by_id: dict[str, AgentSpec] = {}
    for spec in specs:
        if spec.id in by_id:
            raise ValueError(f"duplicate task ID: {spec.id}")
        if spec.cpu_units > budget.cpu_units or spec.memory_mib > budget.memory_mib:
            raise ValueError(f"task {spec.id} exceeds cluster budget")
        by_id[spec.id] = spec
    incoming = {spec.id: len(spec.deps) for spec in specs}
    children: dict[str, list[str]] = {spec.id: [] for spec in specs}
    for spec in specs:
        for dep in spec.deps:
            if dep not in by_id:
                raise ValueError(f"unknown dependency for {spec.id}: {dep}")
            if by_id[dep].tenant != spec.tenant:
                raise ValueError(f"cross-tenant dependency denied: {dep} -> {spec.id}")
            children[dep].append(spec.id)
    ready = sorted(key for key, degree in incoming.items() if degree == 0)
    order: list[str] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for child in sorted(children[current]):
            incoming[child] -= 1
            if incoming[child] == 0:
                ready.append(child)
        ready.sort()
    if len(order) != len(specs):
        raise ValueError("dependency cycle detected")
    return specs, budget, order


def read_plan(path: Path) -> tuple[list[AgentSpec], Budget, list[str]]:
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc.msg}") from exc
    return validate_plan(content)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate AgentOS plan and show DAG without starting agents")
    parser.add_argument("plan", type=Path, help="execution plan JSON")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()
    try:
        specs, budget, order = read_plan(args.plan)
    except (ValueError, OSError) as exc:
        print(f"PLAN INVALID: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps({
            "valid": True,
            "tasks": len(specs),
            "budget": vars(budget),
            "topological_order": order,
            "edges": [{"from": dep, "to": spec.id}
                      for spec in specs for dep in spec.deps],
            "tenants": sorted({spec.tenant for spec in specs}),
        }, ensure_ascii=False, indent=2))
    else:
        print(f"PLAN VALID: {len(specs)} tasks; "
              f"CPU {budget.cpu_units}; memory {budget.memory_mib} MiB")
        print("DAG order: " + " -> ".join(order))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
