"""Function Calling checkpoints (FC): per-call history and non-destructive rollback."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .layerfs import LayerFSClient, LayerFSFailure


def main() -> int:
    parser = argparse.ArgumentParser(description="LayerFS FC call-level and file-level rollback")
    parser.add_argument("--mode", choices=["history", "rewind", "files"], default="files")
    parser.add_argument("--branch", required=True, help="current source branch (never modified)")
    parser.add_argument("--checkpoint", help="immutable Commit/Layer ID for rewind/files")
    parser.add_argument("--path", action="append", dest="paths", help="selected file; repeat for more")
    args = parser.parse_args()
    if args.mode in {"rewind", "files"} and not args.checkpoint:
        parser.error("--checkpoint required for rewind/files")
    if args.mode == "files" and not args.paths:
        parser.error("at least one --path is required")
    if args.mode != "files" and args.paths:
        parser.error("--path applies only to --mode files")
    try:
        client = LayerFSClient()
        if args.mode == "history":
            result = asyncio.run(client.fc_history(args.branch))
        elif args.mode == "rewind":
            result = asyncio.run(client.fc_rewind(args.branch, args.checkpoint))
        else:
            result = asyncio.run(client.fc_restore(args.branch, args.checkpoint, args.paths))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, LayerFSFailure, OSError) as exc:
        print(f"FC refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
