"""Bounded local Unix-domain IPC broker with per-agent capability tokens."""
from __future__ import annotations

import asyncio
import json
import os
import secrets
from collections import defaultdict, deque
from pathlib import Path
from typing import Callable, Awaitable

from .context import ContextStore
from .models import AgentSpec

MAX_MESSAGE = 60 * 1024
INBOX_LIMIT = 128


class AgentBus:
    def __init__(self, socket_path: Path, context: ContextStore,
                 lookup: Callable[[str], AgentSpec | None],
                 spawn: Callable[[str, dict], Awaitable[str]],
                 declare: Callable[[str, list[dict]], Awaitable[list[str]]],
                 audit: Callable[..., None] | None = None):
        self.path = socket_path
        self.context = context
        self.lookup = lookup
        self.spawn = spawn
        self.declare = declare
        self.audit = audit
        self.tokens: dict[str, tuple[str, str]] = {}
        self.queues: dict[str, deque] = defaultdict(deque)
        self.server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        self.server = await asyncio.start_unix_server(self._handle, path=str(self.path), limit=MAX_MESSAGE + 1)
        os.chmod(self.path, 0o600)

    def register(self, spec: AgentSpec) -> str:
        token = secrets.token_hex(32)
        self.tokens[token] = (spec.id, spec.tenant)
        return token

    def unregister(self, token: str) -> None:
        self.tokens.pop(token, None)

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        self.path.unlink(missing_ok=True)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # A handled control is not evidence that its response reached the
        # client, nor that the receiving Agent consumed a queued payload.
        request_id = None
        agent_id = None
        error_code = "ok"
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            if not line or len(line) > MAX_MESSAGE:
                raise ValueError("oversized or empty request")
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            owner = self.tokens.get(request.get("token"))
            if owner is None:
                raise PermissionError("invalid agent capability")
            agent_id, tenant = owner
            op = request.get("op")
            request_id = secrets.token_hex(12)
            observed_op = op if isinstance(op, str) and op in {
                "send", "recv", "context_put", "context_get", "spawn", "declare_tasks"
            } else "unknown"
            if self.audit:
                self.audit("requested", task=agent_id, request_id=request_id,
                           op=observed_op)
            if op == "send":
                target = request.get("to")
                dest = self.lookup(target) if isinstance(target, str) else None
                if not dest or dest.tenant != tenant:
                    raise PermissionError("target is unknown or in another tenant")
                queue = self.queues[target]
                if len(queue) >= INBOX_LIMIT:
                    raise ValueError("target inbox is full")
                payload = request.get("payload")
                if not isinstance(payload, (str, dict, list, int, float, bool, type(None))):
                    raise ValueError("invalid payload")
                if len(json.dumps(payload).encode()) > MAX_MESSAGE // 2:
                    raise ValueError("payload too large")
                queue.append({"from": agent_id, "payload": payload})
                data = {"queued": len(queue)}
            elif op == "recv":
                queue = self.queues[agent_id]
                count = min(32, len(queue))
                data = {"messages": [queue.popleft() for _ in range(count)]}
            elif op == "context_put":
                data = self.context.put(tenant, request.get("key"), request.get("value"))
            elif op == "context_get":
                data = {"value": self.context.get(tenant, request.get("key"))}
            elif op == "spawn":
                data = {"id": await self.spawn(agent_id, request.get("task"))}
            elif op == "declare_tasks":
                ids = await self.declare(agent_id, request.get("tasks"))
                data = {"ids": ids, "count": len(ids)}
            else:
                raise ValueError("unsupported operation")
            result = {"ok": True, "result": data}
        except (ValueError, PermissionError, TypeError, KeyError, json.JSONDecodeError) as exc:
            error_code = "permission_denied" if isinstance(exc, PermissionError) else "invalid_request"
            result = {"ok": False, "error": str(exc)}
        except Exception:
            # Do not expose internal paths, stack frames or credentials to clients.
            error_code = "internal_error"
            result = {"ok": False, "error": "internal broker error"}
        if request_id and agent_id and self.audit:
            self.audit("handled", task=agent_id, request_id=request_id,
                       accepted=result["ok"], code=error_code)
        try:
            writer.write((json.dumps(result, ensure_ascii=False) + "\n").encode())
            await asyncio.wait_for(writer.drain(), timeout=5)
        except (ConnectionError, TimeoutError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
