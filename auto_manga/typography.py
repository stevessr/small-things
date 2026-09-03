from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from .masking import build_region_glyph_mask
from .models import Settings, TextRegion


def _rgb_to_hex(rgb: tuple[int, int, int] | list[int] | np.ndarray) -> str:
    values = [max(0, min(255, int(round(float(value))))) for value in rgb]
    return "#" + "".join(f"{value:02X}" for value in values[:3])


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    clean = value.strip().lstrip("#")
    if len(clean) == 3:
        clean = "".join(char * 2 for char in clean)
    if len(clean) != 6:
        raise ValueError(f"Invalid color: {value}")
    return tuple(int(clean[index:index + 2], 16) for index in (0, 2, 4))


def _linear_channel(value: float) -> float:
    value /= 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _relative_luminance(rgb: tuple[int, int, int] | list[int] | np.ndarray) -> float:
    r, g, b = [_linear_channel(float(value)) for value in rgb[:3]]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    a, b = sorted((_relative_luminance(left), _relative_luminance(right)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def _projection_runs(mask: np.ndarray, axis: int) -> list[int]:
    occupied = np.any(mask > 0, axis=axis).astype(np.uint8)
    if occupied.size == 0 or not occupied.any():
        return []
    # Bridge tiny anti-alias/component gaps before measuring line/column bands.
    kernel = np.ones((5,), dtype=np.uint8)
    bridged = np.convolve(occupied, kernel, mode="same") > 0
    runs: list[int] = []
    start: int | None = None
    for index, value in enumerate(bridged):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append(index - start)
            start = None
    if start is not None:
        runs.append(len(bridged) - start)
    return [value for value in runs if value > 1]


def estimate_source_font_size(mask: np.ndarray, direction: str, fallback: int) -> int:
    if mask.size == 0 or np.count_nonzero(mask) == 0:
        return max(6, fallback)
    # Horizontal writing forms horizontal row bands; vertical writing forms column bands.
    axis = 1 if direction != "vertical" else 0
    runs = _projection_runs(mask, axis)
    if runs:
        extent = float(np.median(runs))
    else:
        ys, xs = np.where(mask > 0)
        extent = float((ys.max() - ys.min() + 1) if direction != "vertical" else (xs.max() - xs.min() + 1))
    # Pillow CJK visible glyph height is typically a little smaller than the nominal point size.
    return max(6, int(round(extent * 1.08)))


def _sample_source_colors(crop: np.ndarray, glyph: np.ndarray, polarity: str) -> tuple[str, str]:
    if crop.size == 0:
        return "#111111", "#FFFFFF"
    core = glyph.copy()
    if np.count_nonzero(core):
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        eroded = cv2.erode(core, kernel, iterations=1)
        if np.count_nonzero(eroded) >= max(3, int(np.count_nonzero(core) * 0.15)):
            core = eroded
    text_pixels = crop[core > 0] if np.count_nonzero(core) else np.empty((0, 3), dtype=np.uint8)

    if np.count_nonzero(glyph):
        ring_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        ring = cv2.dilate(glyph, ring_kernel, iterations=1)
        ring = cv2.bitwise_and(ring, cv2.bitwise_not(glyph))
        background_pixels = crop[ring > 0]
    else:
        background_pixels = np.empty((0, 3), dtype=np.uint8)
    if background_pixels.size < 30:
        background_pixels = crop[glyph == 0] if glyph.size else crop.reshape(-1, 3)

    if text_pixels.size:
        # Median works well for antialiased text cores and is much less sensitive to isolated art pixels.
        text_rgb = np.median(text_pixels, axis=0)
    else:
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        if polarity == "light_on_dark":
            index = gray >= np.percentile(gray, 90)
        else:
            index = gray <= np.percentile(gray, 10)
        fallback_pixels = crop[index]
        text_rgb = np.median(fallback_pixels, axis=0) if fallback_pixels.size else np.array((17, 17, 17))

    if background_pixels.size:
        background_rgb = np.median(background_pixels, axis=0)
    else:
        background_rgb = np.median(crop.reshape(-1, 3), axis=0)
    return _rgb_to_hex(text_rgb), _rgb_to_hex(background_rgb)


def infer_region_style(image: Image.Image, region: TextRegion, settings: Settings) -> dict[str, Any]:
    x1, y1, x2, y2 = region.box
    x1 = max(0, min(image.width, x1)); x2 = max(0, min(image.width, x2))
    y1 = max(0, min(image.height, y1)); y2 = max(0, min(image.height, y2))
    if x2 <= x1 or y2 <= y1:
        return {}
    crop = np.asarray(image.convert("RGB"))[y1:y2, x1:x2]
    glyph = build_region_glyph_mask(image, region, settings, dilate=False)
    text_color, background_color = _sample_source_colors(crop, glyph, region.polarity)
    direction = region.direction if region.direction in {"horizontal", "vertical"} else (
        "vertical" if region.h > region.w * 1.2 else "horizontal"
    )
    preferred_size = estimate_source_font_size(glyph, direction, settings.font_size)
    text_rgb = _hex_to_rgb(text_color)
    bg_rgb = _hex_to_rgb(background_color)
    contrast = contrast_ratio(text_rgb, bg_rgb)
    inferred_stroke = 0 if contrast >= 3.0 and region.region_type != "sfx" else settings.stroke_width
    style = {
        "text_color": text_color,
        "background_color": background_color,
        "font_size": preferred_size,
        "stroke_width": inferred_stroke,
        "contrast": round(contrast, 3),
        "direction": direction,
    }
    region.metadata["source_style"] = style
    return style


def _font_path_for_region(region: TextRegion, settings: Settings) -> str:
    manual = region.metadata.get("render_style") or {}
    if manual.get("font_path"):
        return str(manual["font_path"])
    type_path = {
        "dialogue": settings.dialogue_font_path,
        "narration": settings.narration_font_path,
        "sfx": settings.sfx_font_path,
    }.get(region.region_type, "")
    return type_path or settings.font_path


def resolve_region_style(region: TextRegion, settings: Settings) -> dict[str, Any]:
    manual = region.metadata.get("render_style") or {}
    source = region.metadata.get("source_style") or {}
    use_source = settings.match_source_style and bool(source)

    preferred_size = int(manual.get("font_size") or (source.get("font_size") if use_source else settings.font_size) or settings.font_size)
    preferred_size = max(settings.min_font_size, min(max(settings.font_size, settings.min_font_size), preferred_size))
    text_color = str(manual.get("text_color") or (source.get("text_color") if use_source else settings.text_color) or settings.text_color)

    if "stroke_width" in manual:
        stroke_width = max(0, int(manual["stroke_width"]))
    elif use_source:
        stroke_width = max(0, int(source.get("stroke_width", settings.stroke_width)))
    else:
        stroke_width = max(0, settings.stroke_width)
    stroke_color = str(
        manual.get("stroke_color")
        or (source.get("background_color") if use_source and stroke_width else settings.stroke_color)
        or settings.stroke_color
    )
    line_spacing = float(manual.get("line_spacing", settings.line_spacing))
    return {
        "font_path": _font_path_for_region(region, settings),
        "font_size": preferred_size,
        "min_font_size": max(6, settings.min_font_size),
        "text_color": text_color,
        "stroke_color": stroke_color,
        "stroke_width": stroke_width,
        "line_spacing": max(0.7, min(2.0, line_spacing)),
    }


def _background_reference(image: Image.Image, region: TextRegion) -> np.ndarray:
    source = region.metadata.get("source_style") or {}
    if source.get("background_color"):
        try:
            return np.array(_hex_to_rgb(str(source["background_color"])), dtype=np.float32)
        except ValueError:
            pass
    x1, y1, x2, y2 = region.box
    x1 = max(0, min(image.width - 1, x1)); x2 = max(x1 + 1, min(image.width, x2))
    y1 = max(0, min(image.height - 1, y1)); y2 = max(y1 + 1, min(image.height, y2))
    crop = np.asarray(image.convert("RGB"))[y1:y2, x1:x2]
    if crop.size == 0:
        return np.array((255, 255, 255), dtype=np.float32)
    corners = np.concatenate([
        crop[: max(1, crop.shape[0] // 6), : max(1, crop.shape[1] // 6)].reshape(-1, 3),
        crop[: max(1, crop.shape[0] // 6), -max(1, crop.shape[1] // 6):].reshape(-1, 3),
        crop[-max(1, crop.shape[0] // 6):, : max(1, crop.shape[1] // 6)].reshape(-1, 3),
        crop[-max(1, crop.shape[0] // 6):, -max(1, crop.shape[1] // 6):].reshape(-1, 3),
    ])
    return np.median(corners, axis=0).astype(np.float32)


def _strip_matches(strip: np.ndarray, target: np.ndarray, tolerance: int) -> bool:
    if strip.size == 0:
        return False
    distance = np.sqrt(np.sum((strip.astype(np.float32) - target) ** 2, axis=2))
    allowed = max(8.0, float(tolerance) * math.sqrt(3.0))
    return float(np.count_nonzero(distance <= allowed)) / max(1, distance.size) >= 0.82


def resolve_typeset_box(image: Image.Image, region: TextRegion, settings: Settings) -> tuple[int, int, int, int]:
    override = (region.metadata.get("render_style") or {}).get("box")
    if isinstance(override, (list, tuple)) and len(override) == 4:
        left, top, right, bottom = map(int, override)
        return (
            max(0, min(image.width - 1, left)),
            max(0, min(image.height - 1, top)),
            max(1, min(image.width, right)),
            max(1, min(image.height, bottom)),
        )

    left, top, right, bottom = region.box
    left = max(0, min(image.width - 1, left)); right = max(left + 1, min(image.width, right))
    top = max(0, min(image.height - 1, top)); bottom = max(top + 1, min(image.height, bottom))
    if not settings.auto_expand_typeset_box or region.region_type == "sfx":
        box = (left, top, right, bottom)
        region.metadata["typeset_box"] = list(box)
        return box

    rgb = np.asarray(image.convert("RGB"))
    target = _background_reference(image, region)
    max_x = max(0, int(round(region.w * max(0.0, settings.typeset_expand_ratio))))
    max_y = max(0, int(round(region.h * max(0.0, settings.typeset_expand_ratio))))
    step = 2
    grown_left = grown_right = grown_top = grown_bottom = 0
    changed = True
    while changed:
        changed = False
        if grown_left < max_x and left >= step:
            strip = rgb[top:bottom, left - step:left]
            if _strip_matches(strip, target, settings.typeset_background_tolerance):
                left -= step; grown_left += step; changed = True
        if grown_right < max_x and right + step <= image.width:
            strip = rgb[top:bottom, right:right + step]
            if _strip_matches(strip, target, settings.typeset_background_tolerance):
                right += step; grown_right += step; changed = True
        if grown_top < max_y and top >= step:
            strip = rgb[top - step:top, left:right]
            if _strip_matches(strip, target, settings.typeset_background_tolerance):
                top -= step; grown_top += step; changed = True
        if grown_bottom < max_y and bottom + step <= image.height:
            strip = rgb[bottom:bottom + step, left:right]
            if _strip_matches(strip, target, settings.typeset_background_tolerance):
                bottom += step; grown_bottom += step; changed = True

    box = (left, top, right, bottom)
    region.metadata["typeset_box"] = list(box)
    return box


def validate_font_path(path: str) -> str:
    if not path:
        return ""
    candidate = Path(path).expanduser()
    return str(candidate) if candidate.is_file() else ""
