from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
GENERATED_SUFFIX = ".translated"
CURRENT_SCHEMA_VERSION = 2


@dataclass
class Settings:
    recursive: bool = False
    target_language: str = "zh-CN"

    # Detection / runtime
    detector: str = "auto"
    runtime_profile: str = "auto"
    model_cache_dir: str = ""
    ctd_model_path: str = ""
    dbnet_model_path: str = ""
    detect_sfx: bool = True
    preserve_sfx: bool = True
    translate_sfx: bool = False
    detect_min_area_ratio: float = 0.00008
    detect_max_area_ratio: float = 0.12
    detect_padding: int = 10
    detect_max_side: int = 1800
    detect_min_text_density: float = 0.015
    detect_merge_iou: float = 0.15
    detector_min_confidence: float = 0.35

    # OCR
    ocr_backend: str = "manga_ocr"
    ocr_language: str = "ja"
    vision_base_url: str = "https://api.openai.com/v1"
    vision_api_key: str = ""
    vision_model: str = "gpt-4.1-mini"

    # Translation
    translation_provider: str = "openai_compatible"
    translation_base_url: str = "https://api.openai.com/v1"
    translation_api_key: str = ""
    translation_model: str = "gpt-4.1-mini"
    translation_batch_size: int = 16
    translation_retries: int = 3
    glossary_path: str = ""
    use_translation_memory: bool = True

    # Inpainting / source glyph extraction
    inpainter: str = "auto"
    lama_model_path: str = ""
    inpaint_radius: int = 3
    inpaint_dilate: int = 2
    mask_auto_expand: bool = True
    mask_max_dilate: int = 6
    mask_color_aware: bool = True
    mask_polygon_guard: bool = True
    mask_min_component_area: int = 3
    mask_max_component_ratio: float = 0.30
    mask_max_fill_ratio: float = 0.48

    # Typesetting
    font_path: str = ""
    dialogue_font_path: str = ""
    narration_font_path: str = ""
    sfx_font_path: str = ""
    font_size: int = 42
    min_font_size: int = 14
    text_color: str = "#111111"
    stroke_color: str = "#FFFFFF"
    stroke_width: int = 2
    line_spacing: float = 1.1
    typeset_direction: str = "auto"
    box_margin: int = 8
    match_source_style: bool = True
    auto_expand_typeset_box: bool = True
    typeset_expand_ratio: float = 0.35
    typeset_background_tolerance: int = 36

    # Output / cache
    output_format: str = "png"
    jpeg_quality: int = 95
    keep_project_json: bool = True
    skip_unchanged: bool = True


@dataclass
class TextRegion:
    x: int
    y: int
    w: int
    h: int
    source: str = ""
    translation: str = ""
    direction: str = "auto"
    confidence: float | None = None
    enabled: bool = True
    region_type: str = "unknown"
    polarity: str = "unknown"
    polygon: list[list[int]] | None = None
    mask_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)

    @property
    def box(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.x + self.w, self.y + self.h


@dataclass
class PageJob:
    image: Path
    relative: Path
    status: str = "pending"
    message: str = ""
    quality_score: float | None = None
    needs_review: bool = False
    issue_count: int = 0


def natural_sort_key(value: str) -> tuple:
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value))


def discover_pages(folder: Path, recursive: bool = False, output_dir: Path | None = None) -> list[PageJob]:
    folder = folder.expanduser().resolve()
    output_resolved = output_dir.expanduser().resolve() if output_dir else None
    jobs: list[PageJob] = []
    for path in folder.glob("**/*" if recursive else "*"):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if GENERATED_SUFFIX in path.stem.lower():
            continue
        resolved = path.resolve()
        if output_resolved:
            try:
                resolved.relative_to(output_resolved)
                continue
            except ValueError:
                pass
        jobs.append(PageJob(resolved, resolved.relative_to(folder)))
    return sorted(jobs, key=lambda job: natural_sort_key(str(job.relative).lower()))


def page_output_paths(job: PageJob, output_root: Path, settings: Settings) -> tuple[Path, Path]:
    ext = settings.output_format.lower().lstrip(".")
    parent = output_root / job.relative.parent
    return (
        parent / f"{job.image.stem}{GENERATED_SUFFIX}.{ext}",
        parent / f"{job.image.stem}.manga.json",
    )


def _public_settings(settings: Settings) -> dict[str, Any]:
    data = asdict(settings)
    data.pop("translation_api_key", None)
    data.pop("vision_api_key", None)
    return data


def settings_fingerprint(settings: Settings, stage: str | None = None) -> str:
    data = _public_settings(settings)
    stage_fields: dict[str, set[str]] = {
        "detect": {
            "detector", "runtime_profile", "ctd_model_path", "dbnet_model_path",
            "detect_sfx", "preserve_sfx", "detect_min_area_ratio", "detect_max_area_ratio",
            "detect_padding", "detect_max_side", "detect_min_text_density", "detect_merge_iou",
            "detector_min_confidence",
        },
        "ocr": {"ocr_backend", "ocr_language", "vision_base_url", "vision_model"},
        "translate": {
            "target_language", "translation_provider", "translation_base_url", "translation_model",
            "translation_batch_size", "translation_retries", "glossary_path", "translate_sfx",
        },
        "inpaint": {
            "inpainter", "runtime_profile", "lama_model_path", "inpaint_radius", "inpaint_dilate",
            "mask_auto_expand", "mask_max_dilate", "mask_color_aware", "mask_polygon_guard",
            "mask_min_component_area", "mask_max_component_ratio", "mask_max_fill_ratio", "preserve_sfx",
            "match_source_style",
        },
        "render": {
            "font_path", "dialogue_font_path", "narration_font_path", "sfx_font_path",
            "font_size", "min_font_size", "text_color", "stroke_color", "stroke_width",
            "line_spacing", "typeset_direction", "box_margin", "match_source_style",
            "auto_expand_typeset_box", "typeset_expand_ratio", "typeset_background_tolerance",
            "output_format", "jpeg_quality", "preserve_sfx",
        },
    }
    if stage in stage_fields:
        data = {key: data.get(key) for key in sorted(stage_fields[stage])}
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def page_fingerprint(job: PageJob, settings: Settings) -> str:
    stat = job.image.stat()
    payload = {
        "path": str(job.relative),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "settings": settings_fingerprint(settings),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def stage_fingerprint(job: PageJob, settings: Settings, stage: str, extra: Any = None) -> str:
    stat = job.image.stat()
    payload = {
        "path": str(job.relative),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "settings": settings_fingerprint(settings, stage),
        "extra": extra,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _region_from_dict(item: dict[str, Any]) -> TextRegion:
    allowed = {entry.name for entry in fields(TextRegion)}
    clean = {key: value for key, value in item.items() if key in allowed}
    return TextRegion(**clean)


def migrate_project(data: dict[str, Any]) -> dict[str, Any]:
    version = int(data.get("schema_version", data.get("version", 1)))
    if version > CURRENT_SCHEMA_VERSION:
        raise ValueError(
            f"Project schema {version} is newer than supported schema {CURRENT_SCHEMA_VERSION}. "
            "Please update small-things/auto_manga."
        )
    migrated = dict(data)
    if version == 1:
        migrated.pop("version", None)
        migrated["schema_version"] = 2
        migrated.setdefault("metadata", {})
        migrated.setdefault("quality", {"score": 1.0, "needs_review": False, "issues": []})
        migrated.setdefault("fingerprints", {})
        for region in migrated.get("regions", []):
            region.setdefault("region_type", "unknown")
            region.setdefault("polarity", "unknown")
            region.setdefault("polygon", None)
            region.setdefault("mask_path", None)
            region.setdefault("metadata", {})
            region.setdefault("quality", {})
        version = 2
    migrated["schema_version"] = version
    return migrated


def save_project(
    path: Path,
    job: PageJob,
    settings: Settings,
    regions: list[TextRegion],
    fingerprint: str,
    *,
    metadata: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    fingerprints: dict[str, str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "source": str(job.image),
        "relative": str(job.relative),
        "fingerprint": fingerprint,
        "fingerprints": fingerprints or {},
        "target_language": settings.target_language,
        "metadata": metadata or {},
        "quality": quality or {"score": 1.0, "needs_review": False, "issues": []},
        "regions": [asdict(region) for region in regions],
    }
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    temp.replace(path)


def load_project(path: Path) -> tuple[dict[str, Any], list[TextRegion]]:
    data = migrate_project(json.loads(path.read_text("utf-8")))
    return data, [_region_from_dict(item) for item in data.get("regions", [])]


def page_cleaned_cache_path(job: PageJob, output_root: Path) -> Path:
    return output_root / ".auto-manga-cache" / job.relative.parent / f"{job.image.name}.cleaned.png"
