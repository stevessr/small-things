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


def _threshold_glyphs(channel: np.ndarray, polarity: str) -> np.ndarray:
    blur = cv2.GaussianBlur(channel, (3, 3), 0)
    block = _adaptive_block_size(*channel.shape[:2])
    work = 255 - blur if polarity == "light_on_dark" else blur

    adaptive = cv2.adaptiveThreshold(
        work, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block, 9
    )
    _, otsu = cv2.threshold(work, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel_side = max(3, min(11, ((min(channel.shape[:2]) // 12) | 1)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_side, kernel_side))
    blackhat = cv2.morphologyEx(work, cv2.MORPH_BLACKHAT, kernel)
    _, local = cv2.threshold(blackhat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cv2.bitwise_or(otsu, cv2.bitwise_and(adaptive, local))


def _contrast_fallback(channel: np.ndarray, polarity: str) -> np.ndarray:
    if channel.size == 0:
        return np.zeros_like(channel, dtype=np.uint8)
    low = float(np.percentile(channel, 5))
    high = float(np.percentile(channel, 95))
    if high - low < 12:
        return np.zeros_like(channel, dtype=np.uint8)
    threshold = (low + high) * 0.5
    if polarity == "light_on_dark":
        foreground = channel > threshold
    else:
        foreground = channel < threshold
    return np.where(foreground, 255, 0).astype(np.uint8)


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
        # Long border/panel components are much more dangerous than missing a tiny glyph fragment.
        if aspect > 14 and max(cw / max(w, 1), ch / max(h, 1)) > 0.55:
            continue
        touches = int(x <= 1) + int(y <= 1) + int(x + cw >= w - 1) + int(y + ch >= h - 1)
        if touches and (cw > w * 0.28 or ch > h * 0.28):
            continue
        kept.append((index, area))

    output = np.zeros_like(binary)
    for index, _area in kept:
        output[labels == index] = 255

    # Never allow the refined mask to turn back into a rectangular wipe.
    fill = float(np.count_nonzero(output)) / total
    if fill > settings.mask_max_fill_ratio and kept:
        output[:] = 0
        for index, _area in sorted(kept, key=lambda item: item[1]):
            candidate = output.copy()
            candidate[labels == index] = 255
            if float(np.count_nonzero(candidate)) / total > settings.mask_max_fill_ratio:
                break
            output = candidate
    return output


def _candidate_score(channel: np.ndarray, mask: np.ndarray) -> float:
    count = int(np.count_nonzero(mask))
    if count == 0 or count >= mask.size:
        return -1.0
    inside = channel[mask > 0]
    outside = channel[mask == 0]
    if inside.size == 0 or outside.size == 0:
        return -1.0
    contrast = abs(float(np.median(inside)) - float(np.median(outside)))
    fill = count / max(1, mask.size)
    # Prefer high separation while mildly preferring conservative masks.
    return contrast * (1.15 - min(0.9, fill))


def _mask_for_polarity(crop_rgb: np.ndarray, polarity: str, settings: Settings) -> np.ndarray:
    gray = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2GRAY)
    channels = [gray]
    if settings.mask_color_aware:
        channels.extend(cv2.split(crop_rgb))

    best = np.zeros_like(gray)
    best_score = -1.0
    for channel in channels:
        candidate = _filter_components(_threshold_glyphs(channel, polarity), settings)
        if np.count_nonzero(candidate) == 0:
            candidate = _filter_components(_contrast_fallback(channel, polarity), settings)
        score = _candidate_score(channel, candidate)
        if score > best_score:
            best = candidate
            best_score = score
    return best


def _polygon_guard(
    glyph: np.ndarray,
    region: TextRegion,
    crop_origin: tuple[int, int],
    settings: Settings,
) -> np.ndarray:
    if not settings.mask_polygon_guard or not region.polygon or np.count_nonzero(glyph) == 0:
        return glyph
    try:
        points = np.asarray(region.polygon, dtype=np.int32).reshape(-1, 2).copy()
    except (TypeError, ValueError):
        return glyph
    if len(points) < 3:
        return glyph
    points[:, 0] -= crop_origin[0]
    points[:, 1] -= crop_origin[1]
    points[:, 0] = np.clip(points[:, 0], 0, max(0, glyph.shape[1] - 1))
    points[:, 1] = np.clip(points[:, 1], 0, max(0, glyph.shape[0] - 1))
    hull = cv2.convexHull(points)
    prior = np.zeros_like(glyph)
    cv2.fillConvexPoly(prior, hull, 255)
    radius = max(2, min(settings.mask_max_dilate, settings.inpaint_dilate + 2))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
    prior = cv2.dilate(prior, kernel, iterations=1)
    clipped = cv2.bitwise_and(glyph, prior)
    original_count = int(np.count_nonzero(glyph))
    clipped_count = int(np.count_nonzero(clipped))
    # Bad/partial polygons exist in the wild; only trust the guard when it retains a useful core.
    if clipped_count >= max(3, int(original_count * 0.18)):
        return clipped
    return glyph


def _adaptive_dilate_radius(glyph: np.ndarray, settings: Settings) -> int:
    base = max(0, int(settings.inpaint_dilate))
    if not settings.mask_auto_expand or np.count_nonzero(glyph) == 0:
        return min(base, max(0, settings.mask_max_dilate))
    labels_count, _labels, stats, _ = cv2.connectedComponentsWithStats(glyph, connectivity=8)
    short_sides: list[int] = []
    for index in range(1, labels_count):
        _x, _y, w, h, area = map(int, stats[index])
        if area < max(2, settings.mask_min_component_area):
            continue
        short_sides.append(max(1, min(w, h)))
    inferred = round(float(np.median(short_sides)) * 0.12) if short_sides else 0
    return min(max(0, settings.mask_max_dilate), max(base, inferred))


def build_region_glyph_mask(
    image: Image.Image,
    region: TextRegion,
    settings: Settings,
    *,
    dilate: bool = True,
) -> np.ndarray:
    image_rgb = np.asarray(image.convert("RGB"))
    image_gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
    x1, y1, x2, y2 = region.box
    x1 = max(0, min(image.width, x1)); x2 = max(0, min(image.width, x2))
    y1 = max(0, min(image.height, y1)); y2 = max(0, min(image.height, y2))
    if x2 <= x1 or y2 <= y1:
        return np.zeros((0, 0), dtype=np.uint8)
    crop_rgb = image_rgb[y1:y2, x1:x2]
    crop_gray = image_gray[y1:y2, x1:x2]
    polarity = region.polarity if region.polarity in {"dark_on_light", "light_on_dark"} else detect_polarity(crop_gray)
    region.polarity = polarity

    if polarity in {"mixed", "unknown"}:
        dark = _mask_for_polarity(crop_rgb, "dark_on_light", settings)
        light = _mask_for_polarity(crop_rgb, "light_on_dark", settings)
        dark_fill = np.count_nonzero(dark)
        light_fill = np.count_nonzero(light)
        if min(dark_fill, light_fill) == 0:
            glyph = dark if dark_fill else light
        elif max(dark_fill, light_fill) > min(dark_fill, light_fill) * 2.5:
            glyph = dark if dark_fill < light_fill else light
        else:
            glyph = _filter_components(cv2.bitwise_or(dark, light), settings)
    else:
        glyph = _mask_for_polarity(crop_rgb, polarity, settings)

    glyph = _polygon_guard(glyph, region, (x1, y1), settings)
    if np.count_nonzero(glyph):
        close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        glyph = cv2.morphologyEx(glyph, cv2.MORPH_CLOSE, close_kernel, iterations=1)

    pre_dilate = int(np.count_nonzero(glyph))
    radius = _adaptive_dilate_radius(glyph, settings) if dilate else 0
    if radius > 0 and glyph.size:
        size = radius * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        glyph = cv2.dilate(glyph, kernel, iterations=1)

    fill_ratio = float(np.count_nonzero(glyph)) / max(1, glyph.size)
    region.metadata["mask_fill_ratio"] = round(fill_ratio, 5)
    region.metadata["mask_pixels"] = int(np.count_nonzero(glyph))
    region.metadata["mask_core_pixels"] = pre_dilate
    region.metadata["mask_dilate"] = radius
    region.metadata["mask_mode"] = "color-aware" if settings.mask_color_aware else "grayscale"
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
