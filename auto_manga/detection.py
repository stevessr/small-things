from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np
from PIL import Image

from .models import Settings, TextRegion


def _resize_for_detection(image: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    h, w = image.shape[:2]
    longest = max(h, w)
    if longest <= max_side:
        return image, 1.0
    scale = max_side / float(longest)
    resized = cv2.resize(
        image,
        (max(1, round(w * scale)), max(1, round(h * scale))),
        interpolation=cv2.INTER_AREA,
    )
    return resized, scale


def _candidate_component_mask(gray: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    bw = cv2.adaptiveThreshold(
        blur,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        15,
    )
    labels_count, labels, stats, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
    h, w = gray.shape
    canvas = np.zeros_like(gray)
    min_side = max(2, int(min(h, w) * 0.003))
    max_side = max(min_side + 1, int(min(h, w) * 0.09))
    for index in range(1, labels_count):
        _, _, cw, ch, area = stats[index]
        if area < 5:
            continue
        if cw < min_side / 2 or ch < min_side / 2:
            continue
        if cw > max_side * 2.5 or ch > max_side * 2.5:
            continue
        aspect = cw / max(ch, 1)
        if not 0.125 <= aspect <= 8:
            continue
        canvas[labels == index] = 255
    return canvas


def _boxes_from_grouped_mask(mask: np.ndarray, kernel_size: tuple[int, int]) -> list[tuple[int, int, int, int]]:
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, kernel_size)
    grouped = cv2.dilate(mask, kernel, iterations=1)
    grouped = cv2.morphologyEx(grouped, cv2.MORPH_CLOSE, kernel, iterations=1)
    contours, _ = cv2.findContours(grouped, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return [cv2.boundingRect(contour) for contour in contours]


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union else 0.0


def _intersection_over_min(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    return intersection / max(1, min(aw * ah, bw * bh))


def merge_boxes(
    boxes: Sequence[tuple[int, int, int, int]],
    iou_threshold: float = 0.15,
) -> list[tuple[int, int, int, int]]:
    work = [tuple(map(int, box)) for box in boxes]
    changed = True
    while changed:
        changed = False
        output: list[tuple[int, int, int, int]] = []
        while work:
            base = work.pop()
            bx, by, bw, bh = base
            merged = False
            for index, other in enumerate(work):
                if _iou(base, other) >= iou_threshold or _intersection_over_min(base, other) >= 0.45:
                    ox, oy, ow, oh = other
                    x1, y1 = min(bx, ox), min(by, oy)
                    x2, y2 = max(bx + bw, ox + ow), max(by + bh, oy + oh)
                    work.pop(index)
                    work.append((x1, y1, x2 - x1, y2 - y1))
                    changed = True
                    merged = True
                    break
            if not merged:
                output.append(base)
        work = output
    return sorted(work, key=lambda box: (box[1], box[0]))


def detect_text_regions(image: Image.Image, settings: Settings) -> list[TextRegion]:
    rgb = np.array(image.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    resized, scale = _resize_for_detection(bgr, settings.detect_max_side)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    char_mask = _candidate_component_mask(gray)
    h, w = gray.shape

    short = max(3, round(min(h, w) * 0.008))
    long = max(9, round(min(h, w) * 0.035))
    boxes = _boxes_from_grouped_mask(char_mask, (short, long))
    boxes += _boxes_from_grouped_mask(char_mask, (long, short))
    boxes = merge_boxes(boxes, settings.detect_merge_iou)

    page_area = h * w
    candidates: list[tuple[int, int, int, int]] = []
    for x, y, bw, bh in boxes:
        area_ratio = (bw * bh) / max(1, page_area)
        if not settings.detect_min_area_ratio <= area_ratio <= settings.detect_max_area_ratio:
            continue
        crop = char_mask[y : y + bh, x : x + bw]
        density = float(np.count_nonzero(crop)) / max(1, crop.size)
        if density < settings.detect_min_text_density:
            continue
        candidates.append((x, y, bw, bh))

    inverse = 1.0 / scale
    original_w, original_h = image.size
    regions: list[TextRegion] = []
    pad = settings.detect_padding
    for x, y, bw, bh in candidates:
        x, y, bw, bh = (
            round(x * inverse),
            round(y * inverse),
            round(bw * inverse),
            round(bh * inverse),
        )
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(original_w, x + bw + pad)
        y2 = min(original_h, y + bh + pad)
        if x2 - x1 < 8 or y2 - y1 < 8:
            continue
        direction = "vertical" if (y2 - y1) > (x2 - x1) * 1.15 else "horizontal"
        regions.append(TextRegion(x1, y1, x2 - x1, y2 - y1, direction=direction))
    return regions
