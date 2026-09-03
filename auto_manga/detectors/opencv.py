from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np
from PIL import Image

from ..models import Settings, TextRegion


def _resize_for_detection(image: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    h, w = image.shape[:2]
    longest = max(h, w)
    if longest <= max_side:
        return image, 1.0
    scale = max_side / float(longest)
    return cv2.resize(
        image,
        (max(1, round(w * scale)), max(1, round(h * scale))),
        interpolation=cv2.INTER_AREA,
    ), scale


def _candidate_component_mask(gray: np.ndarray) -> np.ndarray:
    def filtered(binary: np.ndarray) -> np.ndarray:
        labels_count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
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

    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    dark = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15
    )
    inverted = 255 - blur
    light = cv2.adaptiveThreshold(
        inverted, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15
    )
    return cv2.bitwise_or(filtered(dark), filtered(light))


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
    boxes: Sequence[tuple[int, int, int, int]], iou_threshold: float = 0.15
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


def detect_polarity(gray_crop: np.ndarray) -> str:
    if gray_crop.size == 0:
        return "unknown"
    mean = float(np.mean(gray_crop))
    # Text commonly occupies well below 20% of a region. 5/95 percentiles still
    # expose minority foreground strokes while ignoring a few isolated outliers.
    p05 = float(np.percentile(gray_crop, 5))
    p95 = float(np.percentile(gray_crop, 95))
    contrast = p95 - p05
    if contrast < 20:
        return "unknown"
    # Narration boxes / inverted bubbles generally have a dark majority background.
    if mean < 105:
        return "light_on_dark"
    if mean > 150:
        return "dark_on_light"
    return "mixed"


def _estimate_confidence(mask_crop: np.ndarray, box_area_ratio: float) -> float:
    if mask_crop.size == 0:
        return 0.0
    density = float(np.count_nonzero(mask_crop)) / max(1, mask_crop.size)
    density_score = 1.0 - min(1.0, abs(density - 0.16) / 0.24)
    area_score = 1.0 if 0.0002 <= box_area_ratio <= 0.05 else 0.7
    return round(max(0.05, min(0.95, 0.35 + 0.45 * density_score + 0.2 * area_score)), 3)


class OpenCVDetector:
    name = "opencv"

    def __init__(self, settings: Settings):
        self.settings = settings

    def detect(self, image: Image.Image) -> list[TextRegion]:
        settings = self.settings
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
        candidates: list[tuple[int, int, int, int, float]] = []
        for x, y, bw, bh in boxes:
            area_ratio = (bw * bh) / max(1, page_area)
            if not settings.detect_min_area_ratio <= area_ratio <= settings.detect_max_area_ratio:
                continue
            crop = char_mask[y : y + bh, x : x + bw]
            density = float(np.count_nonzero(crop)) / max(1, crop.size)
            if density < settings.detect_min_text_density:
                continue
            candidates.append((x, y, bw, bh, _estimate_confidence(crop, area_ratio)))

        inverse = 1.0 / scale
        original_w, original_h = image.size
        original_gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        regions: list[TextRegion] = []
        pad = settings.detect_padding
        for x, y, bw, bh, confidence in candidates:
            x, y, bw, bh = (
                round(x * inverse), round(y * inverse), round(bw * inverse), round(bh * inverse)
            )
            x1 = max(0, x - pad)
            y1 = max(0, y - pad)
            x2 = min(original_w, x + bw + pad)
            y2 = min(original_h, y + bh + pad)
            if x2 - x1 < 8 or y2 - y1 < 8:
                continue
            direction = "vertical" if (y2 - y1) > (x2 - x1) * 1.15 else "horizontal"
            polarity = detect_polarity(original_gray[y1:y2, x1:x2])
            regions.append(
                TextRegion(
                    x1, y1, x2 - x1, y2 - y1,
                    direction=direction,
                    confidence=confidence,
                    polarity=polarity,
                    region_type="unknown",
                    metadata={"detector": self.name},
                )
            )
        return regions
