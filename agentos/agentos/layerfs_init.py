"""Explicit LayerFS initialization (one-time, includes ignored files)."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .layerfs import LayerFSClient, LayerFSFailure


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize LayerFS 1.1 L0 from repository")
    parser.add_argument("--source", required=True, help="absolute path of the source project directory")
    parser.add_argument("--timeout", type=int, default=300, help="init timeout seconds (1-300)")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 300:
        parser.error("timeout must be in [1,300] seconds")
    try:
        result = asyncio.run(LayerFSClient().initialize(args.source, args.timeout * 1000))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, LayerFSFailure) as exc:
        print(f"LayerFS Init failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
