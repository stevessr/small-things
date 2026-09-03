from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
GENERATED_SUFFIX = ".translated"


@dataclass
class Settings:
    recursive: bool = False
    target_language: str = "zh-CN"
    ocr_backend: str = "manga_ocr"
    ocr_language: str = "ja"
    vision_base_url: str = "https://api.openai.com/v1"
    vision_api_key: str = ""
    vision_model: str = "gpt-4.1-mini"
    translation_provider: str = "openai_compatible"
    translation_base_url: str = "https://api.openai.com/v1"
    translation_api_key: str = ""
    translation_model: str = "gpt-4.1-mini"
    translation_batch_size: int = 16
    translation_retries: int = 3
    glossary_path: str = ""
    detect_min_area_ratio: float = 0.00008
    detect_max_area_ratio: float = 0.12
    detect_padding: int = 10
    detect_max_side: int = 1800
    detect_min_text_density: float = 0.015
    detect_merge_iou: float = 0.15
    inpaint_radius: int = 3
    inpaint_dilate: int = 2
    font_path: str = ""
    font_size: int = 42
    min_font_size: int = 14
    text_color: str = "#111111"
    stroke_color: str = "#FFFFFF"
    stroke_width: int = 2
    line_spacing: float = 1.1
    typeset_direction: str = "auto"
    box_margin: int = 8
    output_format: str = "png"
    jpeg_quality: int = 95
    keep_project_json: bool = True
    skip_unchanged: bool = True
    use_translation_memory: bool = True


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

    @property
    def box(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.x + self.w, self.y + self.h


@dataclass
class PageJob:
    image: Path
    relative: Path
    status: str = "pending"
    message: str = ""


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


def _settings_fingerprint(settings: Settings) -> dict:
    data = asdict(settings)
    data.pop("translation_api_key", None)
    data.pop("vision_api_key", None)
    return data


def page_fingerprint(job: PageJob, settings: Settings) -> str:
    stat = job.image.stat()
    payload = {
        "path": str(job.relative),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "settings": _settings_fingerprint(settings),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def save_project(path: Path, job: PageJob, settings: Settings, regions: list[TextRegion], fingerprint: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "source": str(job.image),
        "relative": str(job.relative),
        "fingerprint": fingerprint,
        "target_language": settings.target_language,
        "regions": [asdict(region) for region in regions],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def load_project(path: Path) -> tuple[dict, list[TextRegion]]:
    data = json.loads(path.read_text("utf-8"))
    return data, [TextRegion(**item) for item in data.get("regions", [])]
