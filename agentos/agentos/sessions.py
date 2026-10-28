"""Read-only retained-run history and integrity verification.

Session metadata/digests are not signed: this detects accidental corruption,
not intentional modifications by someone who can edit both files and manifest.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .artifacts import file_sha256
from .record_index import TraceIndex


def inspect_run(directory: Path) -> dict:
    directory = Path(directory)
    manifest = directory / "manifest.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("missing or symlinked session manifest")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unreadable session manifest: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise ValueError("invalid session manifest schema")
    if data.get("run_id") != directory.name:
        raise ValueError("run_id does not match directory")
    result = {"run_id": directory.name, "status": data.get("status"),
              "exit_code": data.get("exit_code"),
              "started_utc": data.get("started_utc"),
              "finished_utc": data.get("finished_utc"),
              "filesystem": data.get("filesystem"),
              "integrity": "incomplete" if data.get("status") == "running" else "ok",
              "errors": []}
    # An active or crash-abandoned run has no terminal report/digests yet.
    # It is incomplete, not proven corrupt. Do not certify it as valid.
    if result["integrity"] == "incomplete":
        return result
    for label in ("report", "trace"):
        # Never follow paths supplied inside a manifest: only fixed local files.
        path = directory / (label + (".json" if label == "report" else ".jsonl"))
        checksum = data.get(label + "_sha256")
        if path.is_symlink() or not path.is_file():
            result["errors"].append(f"{label}: missing or symlinked")
            continue
        if not isinstance(checksum, str) or re.fullmatch("[a-f0-9]{64}", checksum) is None:
            result["errors"].append(f"{label}: missing SHA-256 digest")
            continue
        if file_sha256(path) != checksum:
            result["errors"].append(f"{label}: checksum mismatch")
    if result["errors"]:
        result["integrity"] = "invalid"
    if result["integrity"] == "ok":
        try:
            report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
            if not isinstance(report, dict) or not isinstance(report.get("tasks"), dict):
                raise ValueError("report does not contain tasks object")
            if data.get("session_id") and report.get("session_id") != data["session_id"]:
                raise ValueError("report and manifest session IDs differ")
            if data.get("session_id"):
                # Same strict parser as the HTTP replay endpoint: validate the
                # complete file, including seq/identity/JSON semantics.
                index = TraceIndex(directory / "trace.jsonl")
                verified = index.read(limit=1)
                if index._scan_pos != (directory / "trace.jsonl").stat().st_size:
                    raise ValueError("final trace contains an incomplete trailing JSONL record")
                if verified["session_id"] != data["session_id"]:
                    raise ValueError("trace has a different session ID")
                if index._last_seq != data.get("last_seq"):
                    raise ValueError("trace final sequence does not match manifest")
            else:
                # Legacy unsigned/unsequenced manifests keep basic JSONL
                # structural validation without inventing a session identity.
                with (directory / "trace.jsonl").open("r", encoding="utf-8") as stream:
                    for line in stream:
                        if line.strip() and not isinstance(json.loads(line), dict):
                            raise ValueError("trace contains a nonobject JSON record")
        except (OSError, UnicodeError, ValueError) as exc:
            result["integrity"] = "invalid"
            result["errors"].append(f"invalid JSON artifact: {exc}")
    return result


def list_runs(root: Path) -> list[dict]:
    root = Path(root)
    if not root.is_dir():
        return []
    runs = []
    for directory in sorted(root.iterdir(), reverse=True):
        if not directory.is_dir() or directory.is_symlink():
            continue
        try:
            if (directory / "manifest.json").is_symlink():
                continue
            meta = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            if not isinstance(meta, dict) or meta.get("run_id") != directory.name:
                continue
            runs.append({"run_id": directory.name,
                         "status": meta.get("status", "unknown"),
                         "exit_code": meta.get("exit_code"),
                         "started_utc": meta.get("started_utc")})
        except (OSError, UnicodeError, ValueError):
            continue
    return runs


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only AgentOS run history")
    parser.add_argument("action", choices=["list", "verify"])
    parser.add_argument("--root", type=Path, default=Path(".agentos/runs"))
    parser.add_argument("--session", type=Path, help="session directory for verify")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()
    if args.action == "list":
        results = list_runs(args.root)
        if args.format == "json":
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            for run in results:
                print(f"{run['run_id']}  {run['status']}  exit={run['exit_code']}")
        return 0
    if args.session is None:
        parser.error("verify requires --session")
    try:
        result = inspect_run(args.session)
    except (ValueError, OSError) as exc:
        print(f"SESSION INVALID: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"{result['run_id']}: {result['status']} integrity={result['integrity']}")
        for error in result["errors"]:
            print(f"  {error}")
    return 0 if result["integrity"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
