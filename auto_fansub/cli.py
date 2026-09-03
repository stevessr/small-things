from __future__ import annotations

import argparse
import os
from pathlib import Path

try:
    from .core import CancelledError, Settings, discover_jobs, job_output_paths, process_job
except ImportError:  # Allow `python cli.py` from the directory.
    from core import CancelledError, Settings, discover_jobs, job_output_paths, process_job


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch ASR/translation/typesetting/hardsub pipeline")
    parser.add_argument("folder", type=Path, help="Input folder containing media files")
    parser.add_argument("-o", "--output", type=Path, help="Output directory")
    parser.add_argument("--recursive", action="store_true", help="Scan subdirectories")
    parser.add_argument("--target", default=None, help="Target language")
    parser.add_argument("--provider", choices=("openai_compatible", "none"), default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key", default=None, help="Defaults to OPENAI_API_KEY")
    parser.add_argument("--model", default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--retries", type=int, default=None)
    parser.add_argument("--asr-model", default=None)
    parser.add_argument("--asr-language", default=None)
    parser.add_argument("--glossary", type=Path, default=None, help="JSON, TSV or source=translation glossary")
    parser.add_argument("--font", default=None)
    parser.add_argument("--mono", action="store_true", help="Do not show source-language line under translation")
    parser.add_argument("--force", action="store_true", help="Ignore state/cache and process every job again")
    parser.add_argument("--no-cache", action="store_true", help="Disable reusable ASR/translation cache")
    parser.add_argument("--no-skip", action="store_true", help="Do not skip unchanged completed jobs")
    parser.add_argument("--scan-only", action="store_true", help="Only print discovered jobs")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    settings = Settings()
    settings.recursive = args.recursive
    settings.translation_api_key = args.api_key if args.api_key is not None else os.getenv("OPENAI_API_KEY", "")
    if args.target:
        settings.target_language = args.target
    if args.provider:
        settings.translation_provider = args.provider
    if args.base_url:
        settings.translation_base_url = args.base_url
    if args.model:
        settings.translation_model = args.model
    if args.batch_size is not None:
        settings.translation_batch_size = max(1, args.batch_size)
    if args.retries is not None:
        settings.translation_retries = max(0, args.retries)
    if args.asr_model:
        settings.asr_model = args.asr_model
    if args.asr_language:
        settings.asr_language = args.asr_language
    if args.glossary:
        settings.glossary_path = str(args.glossary.expanduser().resolve())
    if args.font:
        settings.font_name = args.font
    if args.mono:
        settings.keep_source = False
    if args.no_cache:
        settings.cache_intermediate = False
    if args.no_skip:
        settings.skip_unchanged = False

    output = (args.output or args.folder / "fansub-output").expanduser()
    folder = args.folder.expanduser()
    jobs = discover_jobs(folder, args.recursive, output_dir=output)
    if not jobs:
        print("No media files found.")
        return 2

    if args.scan_only:
        for i, job in enumerate(jobs, 1):
            source = job.subtitle.name if job.subtitle else "ASR"
            ass, video = job_output_paths(job, output, settings)
            print(f"[{i}/{len(jobs)}] {job.media} | source={source} | output={video.name} | ass={ass.name}")
        return 0

    failed = 0
    skipped = 0
    try:
        for i, job in enumerate(jobs, 1):
            print(f"[{i}/{len(jobs)}] {job.media.name}")
            try:
                process_job(
                    job,
                    output,
                    settings,
                    lambda stage, value, msg: print(f"  {stage:9} {value:6.1%} {msg[:100]:100}", end="\r", flush=True),
                    force=args.force,
                )
                if job.status == "skipped":
                    skipped += 1
                print(f"\n  -> {job.status}: {job.message}")
            except CancelledError:
                print("\nCancelled.")
                return 130
            except Exception as exc:
                failed += 1
                print(f"\n  FAILED: {exc}")
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130

    succeeded = len(jobs) - failed - skipped
    print(f"Done: {succeeded} processed, {skipped} skipped, {failed} failed; output={output}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
