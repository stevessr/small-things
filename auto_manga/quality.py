from __future__ import annotations

import math
import re
from typing import Any

from .models import Settings, TextRegion
from .render import assess_region_typesetting


def _issue(code: str, severity: str, message: str, region: int | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if region is not None:
        data["region"] = region
    return data


def _iou(a: TextRegion, b: TextRegion) -> float:
    ax1, ay1, ax2, ay2 = a.box
    bx1, by1, bx2, by2 = b.box
    x1, y1 = max(ax1, bx1), max(ay1, by1)
    x2, y2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = max(1, a.w * a.h + b.w * b.h - inter)
    return inter / union


def _has_textual_characters(text: str) -> bool:
    return bool(re.search(r"[A-Za-z0-9_\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", text))


def evaluate_page_quality(
    image_size: tuple[int, int],
    regions: list[TextRegion],
    settings: Settings,
    *,
    detector_fallbacks: list[str] | None = None,
    inpaint_fallbacks: list[str] | None = None,
) -> dict[str, Any]:
    width, height = image_size
    page_area = max(1, width * height)
    issues: list[dict[str, Any]] = []

    for reason in detector_fallbacks or []:
        issues.append(_issue("detector_fallback", "warning", reason))
    for reason in inpaint_fallbacks or []:
        issues.append(_issue("inpaint_fallback", "warning", reason))

    for index, region in enumerate(regions):
        rissues: list[dict[str, Any]] = []
        x1, y1, x2, y2 = region.box
        area_ratio = max(0, region.w) * max(0, region.h) / page_area
        if x1 < 0 or y1 < 0 or x2 > width or y2 > height or region.w <= 0 or region.h <= 0:
            rissues.append(_issue("bbox_out_of_bounds", "error", f"bbox {region.box} is outside {image_size}", index))
        if region.w < 8 or region.h < 8 or area_ratio < settings.detect_min_area_ratio * 0.3:
            rissues.append(_issue("bbox_too_small", "warning", f"bbox {region.w}x{region.h} is suspiciously small", index))
        if area_ratio > max(settings.detect_max_area_ratio, 0.12):
            rissues.append(_issue("bbox_too_large", "warning", f"bbox covers {area_ratio:.1%} of page", index))
        if region.confidence is not None and region.confidence < settings.detector_min_confidence:
            rissues.append(_issue("detector_low_confidence", "warning", f"detector confidence {region.confidence:.2f}", index))

        preserved_sfx = settings.preserve_sfx and region.region_type == "sfx" and not settings.translate_sfx
        if settings.ocr_backend != "none" and region.enabled and not region.source.strip() and not preserved_sfx:
            rissues.append(_issue("ocr_empty", "error", "OCR returned no text", index))
        if region.metadata.get("ocr_error"):
            rissues.append(_issue("ocr_failed", "error", str(region.metadata["ocr_error"]), index))
        ocr_confidence = region.metadata.get("ocr_confidence")
        if isinstance(ocr_confidence, (int, float)) and float(ocr_confidence) < 0.45:
            rissues.append(_issue("ocr_low_confidence", "warning", f"OCR confidence {float(ocr_confidence):.2f}", index))
        if region.source.strip() and not _has_textual_characters(region.source):
            rissues.append(_issue("ocr_symbols_only", "warning", "OCR result contains only symbols/punctuation", index))
        if "�" in region.source or any(ord(char) < 32 and char not in "\n\t" for char in region.source):
            rissues.append(_issue("ocr_suspicious_text", "warning", "OCR contains replacement/control characters", index))

        if region.enabled and region.source.strip() and not preserved_sfx:
            if settings.translation_provider != "none" and not region.translation.strip():
                rissues.append(_issue("translation_empty", "error", "source text is non-empty but translation is empty", index))
            if region.metadata.get("translation_error"):
                rissues.append(_issue("translation_failed", "error", str(region.metadata["translation_error"]), index))
            if region.translation.strip() and region.translation.strip() == region.source.strip() and settings.target_language.lower() not in {settings.ocr_language.lower(), "none"}:
                rissues.append(_issue("translation_same_as_source", "warning", "translation is identical to source", index))
            if len(region.source.strip()) >= 4 and region.translation.strip():
                ratio = len(region.translation.strip()) / max(1, len(region.source.strip()))
                if ratio < 0.18 or ratio > 4.5:
                    rissues.append(_issue("translation_length_anomaly", "warning", f"translation/source length ratio is {ratio:.2f}", index))

        if region.enabled and not preserved_sfx:
            text = region.translation.strip() or region.source.strip()
            if text:
                metrics = assess_region_typesetting(region, text, settings)
                region.metadata["typeset"] = metrics
                if not metrics["fits"]:
                    rissues.append(_issue("typeset_overflow", "error", "text does not fit even at minimum font size", index))
                elif metrics["font_size"] <= max(settings.min_font_size, 12):
                    rissues.append(_issue("typeset_font_too_small", "warning", f"font size reduced to {metrics['font_size']}", index))
                if region.direction == "vertical" and metrics.get("columns", 0) > 8:
                    rissues.append(_issue("typeset_too_many_columns", "warning", f"vertical layout needs {metrics['columns']} columns", index))

        mask_fill = region.metadata.get("mask_fill_ratio")
        if isinstance(mask_fill, (int, float)) and mask_fill > settings.mask_max_fill_ratio:
            rissues.append(_issue("mask_too_large", "error", f"mask fills {float(mask_fill):.1%} of bbox", index))
        if region.metadata.get("inpaint_fallbacks"):
            rissues.append(_issue("inpaint_region_fallback", "warning", "; ".join(map(str, region.metadata["inpaint_fallbacks"])), index))
        if region.source.strip() and not preserved_sfx and region.metadata.get("mask_pixels") == 0:
            rissues.append(_issue("mask_empty", "warning", "no glyph pixels were selected for inpainting", index))

        region.quality = {
            "issues": rissues,
            "needs_review": any(item["severity"] in {"warning", "error"} for item in rissues),
        }
        issues.extend(rissues)

    for left in range(len(regions)):
        for right in range(left + 1, len(regions)):
            overlap = _iou(regions[left], regions[right])
            if overlap >= 0.65:
                issues.append(_issue("bbox_large_overlap", "warning", f"regions {left} and {right} overlap by {overlap:.0%}"))

    penalty = 0.0
    for item in issues:
        penalty += 0.18 if item["severity"] == "error" else 0.07 if item["severity"] == "warning" else 0.0
    score = round(max(0.0, min(1.0, 1.0 - penalty)), 3)
    return {
        "score": score,
        "needs_review": any(item["severity"] in {"warning", "error"} for item in issues),
        "issues": issues,
    }
