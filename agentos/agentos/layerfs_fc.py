"""File Checkpoints (FC): immutable, path-selected LayerFS restoration."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .layerfs import LayerFSClient, LayerFSFailure


def main() -> int:
    parser = argparse.ArgumentParser(description="LayerFS FC fine-grained rollback")
    parser.add_argument("--branch", required=True, help="current source Branch (untouched)")
    parser.add_argument("--checkpoint", required=True, help="immutable Commit or Layer ID")
    parser.add_argument("--path", required=True, action="append", dest="paths",
                        help="absolute file path to restore; repeat for multiple paths")
    args = parser.parse_args()
    try:
        result = asyncio.run(LayerFSClient().fc_restore(args.branch, args.checkpoint, args.paths))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, LayerFSFailure, OSError) as exc:
        print(f"FC refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
