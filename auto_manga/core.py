"""Public compatibility surface for the auto_manga package."""

from .detection import (
    AutoDetector,
    CTDDetector,
    DBNetDetector,
    DetectorRun,
    OpenCVDetector,
    create_detector,
    detect_text_regions,
    detect_with_backend,
    merge_boxes,
)
from .inpainters import (
    AutoInpainter,
    InpaintRun,
    LaMaInpainter,
    OpenCVInpainter,
    create_inpainter,
    inpaint_with_backend,
)
from .masking import build_region_glyph_mask, build_text_mask
from .models import (
    CURRENT_SCHEMA_VERSION,
    GENERATED_SUFFIX,
    IMAGE_EXTENSIONS,
    PageJob,
    Settings,
    TextRegion,
    discover_pages,
    load_project,
    migrate_project,
    natural_sort_key,
    page_cleaned_cache_path,
    page_fingerprint,
    page_output_paths,
    save_project,
    settings_fingerprint,
    stage_fingerprint,
)
from .pipeline import process_page, render_project
from .providers import (
    glossary_fingerprint,
    load_glossary,
    load_translation_memory,
    normalize_text,
    ocr_regions,
    save_translation_memory,
    translate_regions,
    translation_context_fingerprint,
    translation_memory_key,
)
from .quality import evaluate_page_quality
from .render import (
    assess_region_typesetting,
    erase_original_text,
    erase_original_text_with_report,
    resolve_font,
    save_image,
    typeset_translations,
    wrap_horizontal,
)
from .runtime import inference_size, resolve_runtime_profile

__all__ = [
    "AutoDetector", "AutoInpainter", "CTDDetector", "CURRENT_SCHEMA_VERSION",
    "DBNetDetector", "DetectorRun", "GENERATED_SUFFIX", "IMAGE_EXTENSIONS",
    "InpaintRun", "LaMaInpainter", "OpenCVDetector", "OpenCVInpainter",
    "PageJob", "Settings", "TextRegion", "assess_region_typesetting",
    "build_region_glyph_mask", "build_text_mask", "create_detector", "create_inpainter",
    "detect_text_regions", "detect_with_backend", "discover_pages", "erase_original_text",
    "erase_original_text_with_report", "evaluate_page_quality", "glossary_fingerprint",
    "inference_size", "inpaint_with_backend", "load_glossary", "load_project",
    "load_translation_memory", "merge_boxes", "migrate_project", "natural_sort_key",
    "normalize_text", "ocr_regions", "page_cleaned_cache_path", "page_fingerprint",
    "page_output_paths", "process_page", "render_project", "resolve_font",
    "resolve_runtime_profile", "save_image", "save_project", "save_translation_memory",
    "settings_fingerprint", "stage_fingerprint", "translate_regions",
    "translation_context_fingerprint", "translation_memory_key", "typeset_translations",
    "wrap_horizontal",
]
