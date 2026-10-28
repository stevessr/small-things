"""Synchronous standard-library IPC client for supervised agents."""
from __future__ import annotations

import json
import os
import socket


def request(op: str, **fields):
    address = os.environ["AGENTOS_BUS"]
    token = os.environ["AGENTOS_TOKEN"]
    packet = (json.dumps({"token": token, "op": op, **fields}, ensure_ascii=False) + "\n").encode()
    if len(packet) > 60 * 1024:
        raise ValueError("request too large")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(5)
        conn.connect(address)
        conn.sendall(packet)
        with conn.makefile("rb") as stream:
            response = json.loads(stream.readline(65537))
    if not response.get("ok"):
        raise RuntimeError(response.get("error", "broker failure"))
    return response["result"]
