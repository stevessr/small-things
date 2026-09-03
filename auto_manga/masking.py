from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from .detectors.opencv import detect_polarity
from .models import Settings, TextRegion


def _adaptive_block_size(height: int, width: int) -> int:
    side = max(3, min(height, width))
    block = max(15, min(51, (side // 6) | 1))
    return block if block % 2 == 1 else block + 1


def _threshold_glyphs(gray: np.ndarray, polarity: str) -> np.ndarray:
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    block = _adaptive_block_size(*gray.shape[:2])
    if polarity == "light_on_dark":
        work = 255 - blur
    else:
        work = blur

    adaptive = cv2.adaptiveThreshold(
        work, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block, 9
    )
    _, otsu = cv2.threshold(work, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel_side = max(3, min(11, ((min(gray.shape[:2]) // 12) | 1)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_side, kernel_side))
    blackhat = cv2.morphologyEx(work, cv2.MORPH_BLACKHAT, kernel)
    _, local = cv2.threshold(blackhat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cv2.bitwise_or(cv2.bitwise_and(adaptive, otsu), local)


def _filter_components(binary: np.ndarray, settings: Settings) -> np.ndarray:
    h, w = binary.shape[:2]
    total = max(1, h * w)
    labels_count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    kept: list[tuple[int, int]] = []
    for index in range(1, labels_count):
        x, y, cw, ch, area = map(int, stats[index])
        if area < max(1, settings.mask_min_component_area):
            continue
        if area / total > settings.mask_max_component_ratio:
            continue
        if cw <= 0 or ch <= 0:
            continue
        aspect = max(cw / max(ch, 1), ch / max(cw, 1))
        # Very long components are usually panel/bubble/line-art strokes, not glyph bodies.
        if aspect > 14 and max(cw / max(w, 1), ch / max(h, 1)) > 0.55:
            continue
        touches = int(x <= 1) + int(y <= 1) + int(x + cw >= w - 1) + int(y + ch >= h - 1)
        if touches and (cw > w * 0.28 or ch > h * 0.28):
            continue
        kept.append((index, area))

    output = np.zeros_like(binary)
    for index, _area in kept:
        output[labels == index] = 255

    # Never allow an adaptive mask to degenerate into wiping most of a region.
    fill = float(np.count_nonzero(output)) / total
    if fill > settings.mask_max_fill_ratio and kept:
        output[:] = 0
        for index, area in sorted(kept, key=lambda item: item[1]):
            candidate = output.copy()
            candidate[labels == index] = 255
            if float(np.count_nonzero(candidate)) / total > settings.mask_max_fill_ratio:
                break
            output = candidate
    return output


def build_region_glyph_mask(image: Image.Image, region: TextRegion, settings: Settings) -> np.ndarray:
    image_gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    x1, y1, x2, y2 = region.box
    x1 = max(0, min(image.width, x1)); x2 = max(0, min(image.width, x2))
    y1 = max(0, min(image.height, y1)); y2 = max(0, min(image.height, y2))
    if x2 <= x1 or y2 <= y1:
        return np.zeros((0, 0), dtype=np.uint8)
    crop = image_gray[y1:y2, x1:x2]
    polarity = region.polarity if region.polarity in {"dark_on_light", "light_on_dark"} else detect_polarity(crop)
    region.polarity = polarity

    if polarity == "mixed" or polarity == "unknown":
        dark = _filter_components(_threshold_glyphs(crop, "dark_on_light"), settings)
        light = _filter_components(_threshold_glyphs(crop, "light_on_dark"), settings)
        # Pick the more conservative polarity unless their fill is similar, then union them.
        dark_fill = np.count_nonzero(dark)
        light_fill = np.count_nonzero(light)
        if min(dark_fill, light_fill) == 0:
            glyph = dark if dark_fill else light
        elif max(dark_fill, light_fill) > min(dark_fill, light_fill) * 2.5:
            glyph = dark if dark_fill < light_fill else light
        else:
            glyph = cv2.bitwise_or(dark, light)
            glyph = _filter_components(glyph, settings)
    else:
        glyph = _filter_components(_threshold_glyphs(crop, polarity), settings)

    if settings.inpaint_dilate > 0 and glyph.size:
        size = settings.inpaint_dilate * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        glyph = cv2.dilate(glyph, kernel, iterations=1)

    fill_ratio = float(np.count_nonzero(glyph)) / max(1, glyph.size)
    region.metadata["mask_fill_ratio"] = round(fill_ratio, 5)
    region.metadata["mask_pixels"] = int(np.count_nonzero(glyph))
    return glyph


def build_text_mask(image: Image.Image, regions: list[TextRegion], settings: Settings) -> np.ndarray:
    mask = np.zeros((image.height, image.width), dtype=np.uint8)
    for region in regions:
        if not region.enabled:
            continue
        if settings.preserve_sfx and region.region_type == "sfx" and not settings.translate_sfx:
            region.metadata["inpaint_skipped"] = "preserve_sfx"
            continue
        x1, y1, x2, y2 = region.box
        x1 = max(0, min(image.width, x1)); x2 = max(0, min(image.width, x2))
        y1 = max(0, min(image.height, y1)); y2 = max(0, min(image.height, y2))
        if x2 <= x1 or y2 <= y1:
            continue
        glyph = build_region_glyph_mask(image, region, settings)
        if glyph.size == 0:
            continue
        target = mask[y1:y2, x1:x2]
        gh, gw = glyph.shape[:2]
        th, tw = target.shape[:2]
        if (gh, gw) != (th, tw):
            glyph = cv2.resize(glyph, (tw, th), interpolation=cv2.INTER_NEAREST)
        mask[y1:y2, x1:x2] = np.maximum(target, glyph)
    return mask
