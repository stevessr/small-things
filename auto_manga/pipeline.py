from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from .detectors import detect_with_backend
from .models import (
    PageJob,
    Settings,
    TextRegion,
    load_project,
    page_cleaned_cache_path,
    page_fingerprint,
    page_output_paths,
    save_project,
    stage_fingerprint,
)
from .providers import ocr_regions, translate_regions, translation_context_fingerprint
from .quality import evaluate_page_quality
from .render import erase_original_text_with_report, save_image, typeset_translations


_RERUN_STAGES = {"all", "detect", "ocr", "translate", "inpaint", "render"}


def _emit(callback, stage: str, value: float, message: str) -> None:
    if callback:
        callback(stage, max(0.0, min(1.0, value)), message)


def _region_geometry_state(regions: list[TextRegion]) -> list[dict[str, Any]]:
    return [
        {
            "x": region.x,
            "y": region.y,
            "w": region.w,
            "h": region.h,
            "enabled": region.enabled,
            "region_type": region.region_type,
            "polarity": region.polarity,
            "polygon": region.polygon,
        }
        for region in regions
    ]


def _region_source_state(regions: list[TextRegion]) -> list[dict[str, Any]]:
    return [
        {"source": region.source, "enabled": region.enabled, "region_type": region.region_type}
        for region in regions
    ]


def _region_render_state(regions: list[TextRegion]) -> list[dict[str, Any]]:
    return [
        {
            "x": region.x,
            "y": region.y,
            "w": region.w,
            "h": region.h,
            "source": region.source,
            "translation": region.translation,
            "direction": region.direction,
            "enabled": region.enabled,
            "region_type": region.region_type,
        }
        for region in regions
    ]


def _translation_fingerprint(job: PageJob, settings: Settings, regions: list[TextRegion]) -> str:
    return stage_fingerprint(
        job,
        settings,
        "translate",
        {
            "context": translation_context_fingerprint(settings),
            "regions": _region_source_state(regions),
        },
    )


def _inpaint_fingerprint(job: PageJob, settings: Settings, regions: list[TextRegion]) -> str:
    return stage_fingerprint(job, settings, "inpaint", _region_geometry_state(regions))


def _render_fingerprint(job: PageJob, settings: Settings, regions: list[TextRegion]) -> str:
    return stage_fingerprint(job, settings, "render", _region_render_state(regions))


def _job_message(output_path: Path, quality: dict[str, Any], metadata: dict[str, Any]) -> str:
    parts = [str(output_path)]
    if quality.get("needs_review"):
        parts.append(f"review: {len(quality.get('issues', []))} issue(s)")
    detector_fallbacks = metadata.get("detector_fallbacks") or []
    inpaint_fallbacks = metadata.get("inpaint_fallbacks") or []
    if detector_fallbacks:
        parts.append("detector fallback: " + "; ".join(map(str, detector_fallbacks)))
    if inpaint_fallbacks:
        parts.append("inpaint fallback: " + "; ".join(map(str, inpaint_fallbacks)))
    return " | ".join(parts)


def _apply_job_quality(job: PageJob, quality: dict[str, Any]) -> None:
    job.quality_score = float(quality.get("score", 0.0))
    job.needs_review = bool(quality.get("needs_review", False))
    job.issue_count = len(quality.get("issues", []))


def _save_state(
    project_path: Path,
    job: PageJob,
    settings: Settings,
    regions: list[TextRegion],
    metadata: dict[str, Any],
    quality: dict[str, Any],
    fingerprints: dict[str, str],
) -> None:
    save_project(
        project_path,
        job,
        settings,
        regions,
        page_fingerprint(job, settings),
        metadata=metadata,
        quality=quality,
        fingerprints=fingerprints,
    )


def render_project(
    source_image: Path,
    project_path: Path,
    output_path: Path,
    settings: Settings,
    *,
    output_root: Path | None = None,
) -> Path:
    data, regions = load_project(project_path)
    image = Image.open(source_image).convert("RGB")
    root = (output_root or output_path.parent).expanduser().resolve()
    relative = Path(data.get("relative") or source_image.name)
    job = PageJob(source_image.expanduser().resolve(), relative)
    cache_path = page_cleaned_cache_path(job, root)
    current_inpaint = _inpaint_fingerprint(job, settings, regions)
    stored_inpaint = (data.get("fingerprints") or {}).get("inpaint")
    if cache_path.exists() and stored_inpaint == current_inpaint:
        cleaned = Image.open(cache_path).convert("RGB")
    else:
        run = erase_original_text_with_report(image, regions, settings)
        cleaned = run.image
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cleaned.save(cache_path, format="PNG")
    rendered = typeset_translations(cleaned, regions, settings)
    save_image(rendered, output_path, settings)
    return output_path


def process_page(
    job: PageJob,
    output_root: Path,
    settings: Settings,
    progress=None,
    force: bool = False,
    render_existing_project: bool = False,
    rerun_stage: str | None = None,
) -> PageJob:
    output_root = output_root.expanduser().resolve()
    output_path, project_path = page_output_paths(job, output_root, settings)
    cleaned_cache = page_cleaned_cache_path(job, output_root)

    if rerun_stage is not None:
        rerun_stage = rerun_stage.lower().strip()
        if rerun_stage not in _RERUN_STAGES:
            raise ValueError(f"Unsupported rerun stage: {rerun_stage}")

    if render_existing_project:
        if not project_path.exists():
            raise FileNotFoundError(f"Project does not exist: {project_path}")
        rerun_stage = "render"

    project_data: dict[str, Any] = {}
    regions: list[TextRegion] = []
    metadata: dict[str, Any] = {}
    quality: dict[str, Any] = {"score": 1.0, "needs_review": False, "issues": []}
    stored_fingerprints: dict[str, str] = {}
    has_project = project_path.exists()

    if has_project:
        try:
            project_data, regions = load_project(project_path)
            metadata = dict(project_data.get("metadata") or {})
            quality = dict(project_data.get("quality") or quality)
            stored_fingerprints = dict(project_data.get("fingerprints") or {})
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            if render_existing_project:
                raise
            has_project = False
            project_data = {}
            regions = []
            metadata = {}
            stored_fingerprints = {}

    _emit(progress, "load", 0.02, str(job.relative))
    image = Image.open(job.image).convert("RGB")

    detect_fp = stage_fingerprint(job, settings, "detect")
    force_all = force or rerun_stage == "all"
    upstream_locked = render_existing_project
    need_detect = (
        not has_project
        or force_all
        or rerun_stage == "detect"
        or (not upstream_locked and stored_fingerprints.get("detect") != detect_fp)
    )

    detector_fallbacks: list[str] = list(metadata.get("detector_fallbacks") or [])
    detector_ran = False
    if need_detect and not upstream_locked:
        _emit(progress, "detect", 0.08, f"Detecting text regions ({settings.detector})")
        detector_run = detect_with_backend(image, settings)
        regions = detector_run.regions
        detector_ran = True
        detector_fallbacks = list(detector_run.fallback_reasons)
        metadata["detector"] = detector_run.backend
        metadata["detector_fallbacks"] = detector_fallbacks
        if detector_fallbacks:
            _emit(progress, "detect", 0.16, "Fallback: " + "; ".join(detector_fallbacks))
    elif not metadata.get("detector"):
        metadata["detector"] = settings.detector

    ocr_fp = stage_fingerprint(job, settings, "ocr")
    ocr_errors_present = any(region.metadata.get("ocr_error") for region in regions)
    need_ocr = (
        bool(regions)
        and not upstream_locked
        and (
            force_all
            or detector_ran
            or rerun_stage == "ocr"
            or stored_fingerprints.get("ocr") != ocr_fp
            or ocr_errors_present
        )
    )
    ocr_ran = False
    if need_ocr:
        _emit(progress, "ocr", 0.22, f"OCR ({settings.ocr_backend})")
        ocr_regions(image, regions, settings, progress)
        ocr_ran = True

    translate_fp = _translation_fingerprint(job, settings, regions)
    translation_errors_present = any(region.metadata.get("translation_error") for region in regions)
    need_translate = (
        bool(regions)
        and not upstream_locked
        and (
            force_all
            or detector_ran
            or ocr_ran
            or rerun_stage == "translate"
            or stored_fingerprints.get("translate") != translate_fp
            or translation_errors_present
        )
    )
    translation_ran = False
    if need_translate:
        _emit(progress, "translate", 0.55, f"Translating ({settings.translation_provider})")
        translate_regions(regions, settings, output_root, progress)
        translation_ran = True
        translate_fp = _translation_fingerprint(job, settings, regions)

    inpaint_fp = _inpaint_fingerprint(job, settings, regions)
    need_inpaint = bool(regions) and (
        force_all
        or detector_ran
        or rerun_stage in {"detect", "inpaint"}
        or stored_fingerprints.get("inpaint") != inpaint_fp
        or not cleaned_cache.exists()
    )

    inpaint_fallbacks: list[str] = list(metadata.get("inpaint_fallbacks") or [])
    inpaint_ran = False
    cleaned: Image.Image | None = None
    if need_inpaint:
        _emit(progress, "inpaint", 0.78, f"Removing source text ({settings.inpainter})")
        inpaint_run = erase_original_text_with_report(image, regions, settings)
        cleaned = inpaint_run.image
        inpaint_ran = True
        inpaint_fallbacks = list(inpaint_run.fallback_reasons)
        metadata["inpainter"] = inpaint_run.backend
        metadata["inpaint_fallbacks"] = inpaint_fallbacks
        cleaned_cache.parent.mkdir(parents=True, exist_ok=True)
        cleaned.save(cleaned_cache, format="PNG")
        metadata["cleaned_cache"] = cleaned_cache.relative_to(output_root).as_posix()
        if inpaint_fallbacks:
            _emit(progress, "inpaint", 0.84, "Fallback: " + "; ".join(inpaint_fallbacks))
    elif cleaned_cache.exists():
        cleaned = Image.open(cleaned_cache).convert("RGB")

    if not regions:
        quality = evaluate_page_quality(
            image.size,
            regions,
            settings,
            detector_fallbacks=detector_fallbacks,
            inpaint_fallbacks=[],
        )
        fingerprints = {
            "detect": detect_fp,
            "ocr": ocr_fp,
            "translate": _translation_fingerprint(job, settings, regions),
            "inpaint": _inpaint_fingerprint(job, settings, regions),
            "render": _render_fingerprint(job, settings, regions),
        }
        _save_state(project_path, job, settings, regions, metadata, quality, fingerprints)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not output_path.exists() or need_detect or force_all:
            shutil.copy2(job.image, output_path)
        _apply_job_quality(job, quality)
        job.status = "done"
        job.message = _job_message(output_path, quality, metadata)
        _emit(progress, "done", 1.0, job.message)
        return job

    render_fp = _render_fingerprint(job, settings, regions)
    need_render = (
        force_all
        or detector_ran
        or translation_ran
        or inpaint_ran
        or rerun_stage in {"detect", "ocr", "translate", "inpaint", "render"}
        or stored_fingerprints.get("render") != render_fp
        or not output_path.exists()
    )

    if not need_render and settings.skip_unchanged:
        quality = evaluate_page_quality(
            image.size,
            regions,
            settings,
            detector_fallbacks=detector_fallbacks,
            inpaint_fallbacks=inpaint_fallbacks,
        )
        fingerprints = {
            "detect": detect_fp,
            "ocr": ocr_fp,
            "translate": translate_fp,
            "inpaint": inpaint_fp,
            "render": render_fp,
        }
        _save_state(project_path, job, settings, regions, metadata, quality, fingerprints)
        _apply_job_quality(job, quality)
        job.status = "skipped"
        job.message = "unchanged"
        _emit(progress, "skip", 1.0, str(job.relative))
        return job

    if cleaned is None:
        # Render-only after a missing/stale cache rebuilds cleaning, but never OCR/translation.
        _emit(progress, "inpaint", 0.80, "Rebuilding cleaned image cache")
        inpaint_run = erase_original_text_with_report(image, regions, settings)
        cleaned = inpaint_run.image
        inpaint_fallbacks = list(inpaint_run.fallback_reasons)
        metadata["inpainter"] = inpaint_run.backend
        metadata["inpaint_fallbacks"] = inpaint_fallbacks
        cleaned_cache.parent.mkdir(parents=True, exist_ok=True)
        cleaned.save(cleaned_cache, format="PNG")
        metadata["cleaned_cache"] = cleaned_cache.relative_to(output_root).as_posix()
        inpaint_fp = _inpaint_fingerprint(job, settings, regions)

    _emit(progress, "typeset", 0.91, "Typesetting translations")
    rendered = typeset_translations(cleaned, regions, settings)
    save_image(rendered, output_path, settings)

    quality = evaluate_page_quality(
        image.size,
        regions,
        settings,
        detector_fallbacks=detector_fallbacks,
        inpaint_fallbacks=inpaint_fallbacks,
    )
    fingerprints = {
        "detect": detect_fp,
        "ocr": ocr_fp,
        "translate": translate_fp,
        "inpaint": inpaint_fp,
        "render": _render_fingerprint(job, settings, regions),
    }
    metadata["runtime_profile"] = settings.runtime_profile
    _save_state(project_path, job, settings, regions, metadata, quality, fingerprints)

    _apply_job_quality(job, quality)
    job.status = "done"
    job.message = _job_message(output_path, quality, metadata)
    _emit(progress, "done", 1.0, job.message)
    return job
