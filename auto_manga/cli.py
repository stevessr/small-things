from __future__ import annotations

import argparse
import os
from pathlib import Path

try:
    from .core import Settings, discover_pages, page_output_paths, process_page
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from auto_manga.core import Settings, discover_pages, page_output_paths, process_page


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="One-click manga OCR / translation / cleaning / typesetting")
    p.add_argument("folder", type=Path, help="Folder containing manga pages")
    p.add_argument("-o", "--output", type=Path, help="Output directory (default: <folder>/manga-output)")
    p.add_argument("--recursive", action="store_true")
    p.add_argument("--scan-only", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--render-existing", action="store_true", help="Render existing .manga.json without OCR/translation")

    p.add_argument("--ocr", choices=("manga_ocr", "openai_vision", "none"), default="manga_ocr")
    p.add_argument("--ocr-language", default="ja")
    p.add_argument("--vision-base-url", default=None)
    p.add_argument("--vision-api-key", default=None)
    p.add_argument("--vision-model", default=None)

    p.add_argument("--translator", choices=("openai_compatible", "none"), default="openai_compatible")
    p.add_argument("--base-url", default=None)
    p.add_argument("--api-key", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--target", default="zh-CN")
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--glossary", type=Path)
    p.add_argument("--no-tm", action="store_true")

    p.add_argument("--direction", choices=("auto", "horizontal", "vertical"), default="auto")
    p.add_argument("--font", type=Path)
    p.add_argument("--font-size", type=int, default=42)
    p.add_argument("--min-font-size", type=int, default=14)
    p.add_argument("--text-color", default="#111111")
    p.add_argument("--stroke-color", default="#FFFFFF")
    p.add_argument("--stroke-width", type=int, default=2)
    p.add_argument("--inpaint-radius", type=int, default=3)
    p.add_argument("--format", choices=("png", "jpg", "jpeg", "webp"), default="png")
    p.add_argument("--no-skip", action="store_true")
    return p


def settings_from_args(args: argparse.Namespace) -> Settings:
    s = Settings()
    s.recursive = args.recursive
    s.ocr_backend = args.ocr
    s.ocr_language = args.ocr_language
    s.vision_api_key = args.vision_api_key if args.vision_api_key is not None else os.getenv("OPENAI_API_KEY", "")
    if args.vision_base_url:
        s.vision_base_url = args.vision_base_url
    if args.vision_model:
        s.vision_model = args.vision_model

    s.translation_provider = args.translator
    s.translation_api_key = args.api_key if args.api_key is not None else os.getenv("OPENAI_API_KEY", "")
    if args.base_url:
        s.translation_base_url = args.base_url
    if args.model:
        s.translation_model = args.model
    s.target_language = args.target
    s.translation_batch_size = max(1, args.batch_size)
    s.translation_retries = max(0, args.retries)
    s.glossary_path = str(args.glossary.expanduser().resolve()) if args.glossary else ""
    s.use_translation_memory = not args.no_tm

    s.typeset_direction = args.direction
    s.font_path = str(args.font.expanduser().resolve()) if args.font else ""
    s.font_size = max(6, args.font_size)
    s.min_font_size = max(6, min(args.min_font_size, s.font_size))
    s.text_color = args.text_color
    s.stroke_color = args.stroke_color
    s.stroke_width = max(0, args.stroke_width)
    s.inpaint_radius = max(1, args.inpaint_radius)
    s.output_format = args.format
    s.skip_unchanged = not args.no_skip
    return s


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    folder = args.folder.expanduser().resolve()
    output = (args.output or folder / "manga-output").expanduser().resolve()
    settings = settings_from_args(args)
    pages = discover_pages(folder, args.recursive, output)
    if not pages:
        print("No manga pages found.")
        return 2

    if args.scan_only:
        for i, job in enumerate(pages, 1):
            out, project = page_output_paths(job, output, settings)
            print(f"[{i}/{len(pages)}] {job.relative} -> {out.relative_to(output)} | project={project.relative_to(output)}")
        return 0

    failed = skipped = 0
    for i, job in enumerate(pages, 1):
        print(f"[{i}/{len(pages)}] {job.relative}")
        try:
            process_page(
                job,
                output,
                settings,
                lambda stage, value, message: print(
                    f"  {stage:10} {value:6.1%} {message[:90]:90}",
                    end="\r",
                    flush=True,
                ),
                force=args.force,
                render_existing_project=args.render_existing,
            )
            if job.status == "skipped":
                skipped += 1
            print(f"\n  -> {job.status}: {job.message}")
        except KeyboardInterrupt:
            print("\nCancelled.")
            return 130
        except Exception as exc:
            failed += 1
            print(f"\n  FAILED: {exc}")

    ok = len(pages) - failed - skipped
    print(f"Done: {ok} processed, {skipped} skipped, {failed} failed; output={output}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
