"""Compressed, tenant-scoped prompt/context byte store (NOT a GPU KV cache)."""
from __future__ import annotations

import sqlite3
import zlib
from pathlib import Path

MAX_VALUE = 60 * 1024


class ContextStore:
    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS context (
            tenant TEXT NOT NULL, key TEXT NOT NULL,
            codec TEXT NOT NULL, payload BLOB NOT NULL, raw_size INTEGER NOT NULL,
            PRIMARY KEY(tenant, key))""")
        self.db.commit()
        self.hits = 0
        self.misses = 0
        self.raw_bytes = 0
        self.stored_bytes = 0

    def put(self, tenant: str, key: str, value: str) -> dict:
        if not isinstance(value, str) or not isinstance(key, str) or not 1 <= len(key) <= 128:
            raise ValueError("invalid key or context value")
        raw = value.encode("utf-8")
        if len(raw) > MAX_VALUE:
            raise ValueError("context payload exceeds 60 KiB")
        compressed = zlib.compress(raw, level=6)
        codec, payload = ("zlib", compressed) if len(compressed) < len(raw) else ("raw", raw)
        self.db.execute("INSERT OR REPLACE INTO context VALUES (?, ?, ?, ?, ?)",
                        (tenant, key, codec, payload, len(raw)))
        self.db.commit()
        self.raw_bytes += len(raw)
        self.stored_bytes += len(payload)
        return {"raw_bytes": len(raw), "stored_bytes": len(payload), "codec": codec}

    def get(self, tenant: str, key: str) -> str | None:
        row = self.db.execute("SELECT codec, payload, raw_size FROM context WHERE tenant=? AND key=?",
                              (tenant, key)).fetchone()
        if row is None:
            self.misses += 1
            return None
        self.hits += 1
        codec, payload, size = row
        if codec == "raw":
            data = payload
        elif codec == "zlib":
            # Reject decompression bombs, including previously corrupted DB records.
            if not 0 <= size <= MAX_VALUE:
                raise ValueError("invalid stored length")
            obj = zlib.decompressobj()
            data = obj.decompress(payload, size + 1)
            if obj.unconsumed_tail or not obj.eof or len(data) != size:
                raise ValueError("corrupt compressed context")
        else:
            raise ValueError("unknown context codec")
        if len(data) > MAX_VALUE or len(data) != size:
            raise ValueError("invalid context length")
        return data.decode("utf-8")

    def stats(self) -> dict:
        return {"hits": self.hits, "misses": self.misses, "written_raw_bytes": self.raw_bytes,
                "written_stored_bytes": self.stored_bytes,
                "compression_ratio": round(self.stored_bytes / max(1, self.raw_bytes), 4)}

    def close(self) -> None:
        self.db.close()
