from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image

from .detection import detect_text_regions
from .models import (
    PageJob,
    Settings,
    load_project,
    page_fingerprint,
    page_output_paths,
    save_project,
)
from .providers import ocr_regions, translate_regions
from .render import erase_original_text, save_image, typeset_translations


def _emit(callback, stage: str, value: float, message: str) -> None:
    if callback:
        callback(stage, max(0.0, min(1.0, value)), message)


def render_project(
    source_image: Path,
    project_path: Path,
    output_path: Path,
    settings: Settings,
) -> Path:
    _, regions = load_project(project_path)
    image = Image.open(source_image).convert("RGB")
    cleaned = erase_original_text(image, regions, settings)
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
) -> PageJob:
    output_root = output_root.expanduser().resolve()
    output_path, project_path = page_output_paths(job, output_root, settings)
    fingerprint = page_fingerprint(job, settings)

    if render_existing_project and project_path.exists():
        _emit(progress, "render", 0.1, "Rendering edited project")
        render_project(job.image, project_path, output_path, settings)
        job.status = "done"
        job.message = str(output_path)
        _emit(progress, "done", 1.0, str(output_path))
        return job

    if not force and settings.skip_unchanged and output_path.exists() and project_path.exists():
        try:
            project_data, _ = load_project(project_path)
            if project_data.get("fingerprint") == fingerprint:
                job.status = "skipped"
                job.message = "unchanged"
                _emit(progress, "skip", 1.0, str(job.relative))
                return job
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    _emit(progress, "load", 0.02, str(job.relative))
    image = Image.open(job.image).convert("RGB")
    _emit(progress, "detect", 0.05, "Detecting text regions")
    regions = detect_text_regions(image, settings)

    if not regions:
        save_project(project_path, job, settings, [], fingerprint)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(job.image, output_path)
        job.status = "done"
        job.message = "no text regions detected; copied original"
        _emit(progress, "done", 1.0, job.message)
        return job

    ocr_regions(image, regions, settings, progress)
    if settings.ocr_backend != "none":
        regions = [region for region in regions if region.source.strip()]
    translate_regions(regions, settings, output_root, progress)

    # Editable project JSON is the source of truth, not the rasterized output.
    save_project(project_path, job, settings, regions, fingerprint)
    _emit(progress, "inpaint", 0.82, "Removing source text")
    cleaned = erase_original_text(image, regions, settings)
    _emit(progress, "typeset", 0.90, "Typesetting translations")
    rendered = typeset_translations(cleaned, regions, settings)
    save_image(rendered, output_path, settings)

    job.status = "done"
    job.message = str(output_path)
    _emit(progress, "done", 1.0, str(output_path))
    return job
