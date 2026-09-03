"""Public compatibility surface for the auto_manga package."""

from .detection import detect_text_regions, merge_boxes
from .models import (
    GENERATED_SUFFIX,
    IMAGE_EXTENSIONS,
    PageJob,
    Settings,
    TextRegion,
    discover_pages,
    load_project,
    natural_sort_key,
    page_fingerprint,
    page_output_paths,
    save_project,
)
from .pipeline import process_page, render_project
from .providers import (
    load_glossary,
    load_translation_memory,
    normalize_text,
    ocr_regions,
    save_translation_memory,
    translate_regions,
    translation_memory_key,
)
from .render import (
    build_text_mask,
    erase_original_text,
    resolve_font,
    save_image,
    typeset_translations,
    wrap_horizontal,
)

__all__ = [
    "GENERATED_SUFFIX",
    "IMAGE_EXTENSIONS",
    "PageJob",
    "Settings",
    "TextRegion",
    "build_text_mask",
    "detect_text_regions",
    "discover_pages",
    "erase_original_text",
    "load_glossary",
    "load_project",
    "load_translation_memory",
    "merge_boxes",
    "natural_sort_key",
    "normalize_text",
    "ocr_regions",
    "page_fingerprint",
    "page_output_paths",
    "process_page",
    "render_project",
    "resolve_font",
    "save_image",
    "save_project",
    "save_translation_memory",
    "translate_regions",
    "translation_memory_key",
    "typeset_translations",
    "wrap_horizontal",
]
