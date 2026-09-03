from __future__ import annotations

import argparse
import os
from pathlib import Path

try:
    from .core import Settings, discover_pages, load_project, page_output_paths, process_page
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from auto_manga.core import Settings, discover_pages, load_project, page_output_paths, process_page


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="One-click manga OCR / translation / cleaning / typesetting")
    p.add_argument("folder", type=Path, help="Folder containing manga pages")
    p.add_argument("-o", "--output", type=Path, help="Output directory (default: <folder>/manga-output)")
    p.add_argument("--recursive", action="store_true")
    p.add_argument("--scan-only", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--review-only", action="store_true", help="Only process pages whose project is marked needs_review")
    p.add_argument(
        "--rerun",
        choices=("all", "detect", "ocr", "translate", "inpaint", "render"),
        help="Force one pipeline stage (and required downstream work) without throwing away project edits",
    )
    p.add_argument(
        "--render-existing",
        action="store_true",
        help="Compatibility alias for --rerun render; never reruns detect/OCR/translation",
    )

    p.add_argument("--detector", choices=("auto", "ctd", "dbnet", "opencv"), default="auto")
    p.add_argument("--inpainter", choices=("auto", "lama", "opencv"), default="auto")
    p.add_argument(
        "--runtime-profile",
        choices=("auto", "cpu", "low_vram", "balanced", "quality"),
        default="auto",
    )
    p.add_argument("--model-cache", type=Path, help="Override ~/.cache/small-things/auto-manga")
    p.add_argument("--ctd-model", type=Path, help="Use a local CTD ONNX model")
    p.add_argument("--dbnet-model", type=Path, help="Use a local DBNet ONNX model")
    p.add_argument("--lama-model", type=Path, help="Use a local trusted LaMa model")
    p.add_argument("--detect-sfx", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--preserve-sfx", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--translate-sfx", action="store_true")

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

    cleaning = p.add_argument_group("cleaning / inpainting")
    cleaning.add_argument("--inpaint-radius", type=int, default=3)
    cleaning.add_argument("--inpaint-dilate", type=int, default=2, help="Minimum mask expansion in pixels")
    cleaning.add_argument("--mask-auto-expand", action=argparse.BooleanOptionalAction, default=True)
    cleaning.add_argument("--mask-max-dilate", type=int, default=6)
    cleaning.add_argument("--mask-color-aware", action=argparse.BooleanOptionalAction, default=True)
    cleaning.add_argument("--mask-polygon-guard", action=argparse.BooleanOptionalAction, default=True)

    typography = p.add_argument_group("replacement typography")
    typography.add_argument("--direction", choices=("auto", "horizontal", "vertical"), default="auto")
    typography.add_argument("--font", type=Path)
    typography.add_argument("--dialogue-font", type=Path)
    typography.add_argument("--narration-font", type=Path)
    typography.add_argument("--sfx-font", type=Path)
    typography.add_argument("--font-size", type=int, default=42)
    typography.add_argument("--min-font-size", type=int, default=14)
    typography.add_argument("--text-color", default="#111111")
    typography.add_argument("--stroke-color", default="#FFFFFF")
    typography.add_argument("--stroke-width", type=int, default=2)
    typography.add_argument("--match-source-style", action=argparse.BooleanOptionalAction, default=True)
    typography.add_argument("--auto-expand-typeset-box", action=argparse.BooleanOptionalAction, default=True)
    typography.add_argument("--typeset-expand-ratio", type=float, default=0.35)
    typography.add_argument("--typeset-bg-tolerance", type=int, default=36)

    p.add_argument("--format", choices=("png", "jpg", "jpeg", "webp"), default="png")
    p.add_argument("--no-skip", action="store_true")
    return p


def _resolved(value: Path | None) -> str:
    return str(value.expanduser().resolve()) if value else ""


def settings_from_args(args: argparse.Namespace) -> Settings:
    s = Settings()
    s.recursive = args.recursive
    s.detector = args.detector
    s.inpainter = args.inpainter
    s.runtime_profile = args.runtime_profile
    s.model_cache_dir = _resolved(args.model_cache)
    s.ctd_model_path = _resolved(args.ctd_model)
    s.dbnet_model_path = _resolved(args.dbnet_model)
    s.lama_model_path = _resolved(args.lama_model)
    s.detect_sfx = args.detect_sfx
    s.preserve_sfx = args.preserve_sfx
    s.translate_sfx = args.translate_sfx

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
    s.glossary_path = _resolved(args.glossary)
    s.use_translation_memory = not args.no_tm

    s.inpaint_radius = max(1, args.inpaint_radius)
    s.inpaint_dilate = max(0, args.inpaint_dilate)
    s.mask_auto_expand = args.mask_auto_expand
    s.mask_max_dilate = max(s.inpaint_dilate, args.mask_max_dilate)
    s.mask_color_aware = args.mask_color_aware
    s.mask_polygon_guard = args.mask_polygon_guard

    s.typeset_direction = args.direction
    s.font_path = _resolved(args.font)
    s.dialogue_font_path = _resolved(args.dialogue_font)
    s.narration_font_path = _resolved(args.narration_font)
    s.sfx_font_path = _resolved(args.sfx_font)
    s.font_size = max(6, args.font_size)
    s.min_font_size = max(6, min(args.min_font_size, s.font_size))
    s.text_color = args.text_color
    s.stroke_color = args.stroke_color
    s.stroke_width = max(0, args.stroke_width)
    s.match_source_style = args.match_source_style
    s.auto_expand_typeset_box = args.auto_expand_typeset_box
    s.typeset_expand_ratio = max(0.0, min(2.0, args.typeset_expand_ratio))
    s.typeset_background_tolerance = max(0, min(255, args.typeset_bg_tolerance))

    s.output_format = args.format
    s.skip_unchanged = not args.no_skip
    return s


def _needs_review(job, output: Path, settings: Settings) -> bool:
    _out, project = page_output_paths(job, output, settings)
    if not project.exists():
        return False
    try:
        data, _regions = load_project(project)
        return bool((data.get("quality") or {}).get("needs_review"))
    except Exception:
        return True


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    folder = args.folder.expanduser().resolve()
    output = (args.output or folder / "manga-output").expanduser().resolve()
    settings = settings_from_args(args)
    pages = discover_pages(folder, args.recursive, output)
    if not pages:
        print("No manga pages found.")
        return 2

    if args.review_only:
        pages = [job for job in pages if _needs_review(job, output, settings)]
        if not pages:
            print("No pages currently need review.")
            return 0

    if args.scan_only:
        for i, job in enumerate(pages, 1):
            out, project = page_output_paths(job, output, settings)
            review = " review" if _needs_review(job, output, settings) else ""
            print(
                f"[{i}/{len(pages)}] {job.relative} -> {out.relative_to(output)} "
                f"| project={project.relative_to(output)}{review}"
            )
        return 0

    failed = skipped = review_count = 0
    rerun = "render" if args.render_existing else args.rerun
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
                rerun_stage=rerun,
            )
            if job.status == "skipped":
                skipped += 1
            if job.needs_review:
                review_count += 1
            quality = "" if job.quality_score is None else f" quality={job.quality_score:.3f} issues={job.issue_count}"
            print(f"\n  -> {job.status}:{quality} {job.message}")
        except KeyboardInterrupt:
            print("\nCancelled.")
            return 130
        except Exception as exc:
            failed += 1
            print(f"\n  FAILED: {exc}")

    ok = len(pages) - failed - skipped
    print(
        f"Done: {ok} processed, {skipped} skipped, {failed} failed, "
        f"{review_count} need review; output={output}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
