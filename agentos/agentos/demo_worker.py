"""Real subprocess clients for the example: dynamic tasks, context and IPC."""
from __future__ import annotations

import os
import sys

from .client import request


def main() -> None:
    role = sys.argv[1]
    if role == "plan":
        request("context_put", key="task-context",
                value="Analyze system call traces and produce an incident report. " * 120)
        child = {"id": "audit", "kind": "tool", "argv": [sys.executable, "-m",
                 "agentos.demo_worker", "audit"], "memory_mib": 128}
        request("spawn", task=child)
        request("send", to="audit", payload={"job": "independent verification"})
        print("planning complete; spawned audit")
    elif role == "research":
        value = request("context_get", key="task-context")["value"]
        assert value and "incident" in value
        request("send", to="report", payload={"finding": "trace anomalies found", "context_chars": len(value)})
        print("research complete with reused context")
    elif role == "report":
        messages = request("recv")["messages"]
        assert messages and messages[0]["payload"]["finding"] == "trace anomalies found"
        print(f"assembled report from {len(messages)} message(s)")
    elif role == "audit":
        assert request("context_get", key="task-context")["value"]
        assert request("recv")["messages"][0]["payload"]["job"] == "independent verification"
        print("audit complete")
    else:
        raise ValueError(f"unknown role {role}")


if __name__ == "__main__":
    main()
