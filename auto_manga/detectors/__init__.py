from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from ..models import Settings, TextRegion
from .base import DetectorRun, DetectorUnavailable, TextDetector
from .ctd import CTDDetector
from .dbnet import DBNetDetector
from .opencv import OpenCVDetector, merge_boxes


def create_detector(name: str, settings: Settings) -> TextDetector:
    name = name.lower().strip()
    if name == "opencv":
        return OpenCVDetector(settings)
    if name == "ctd":
        return CTDDetector(settings)
    if name == "dbnet":
        return DBNetDetector(settings)
    if name == "auto":
        return AutoDetector(settings)
    raise ValueError(f"Unsupported detector backend: {name}")


def _backend_chain(requested: str) -> tuple[str, ...]:
    requested = requested.lower().strip()
    if requested in {"auto", "ctd"}:
        return ("ctd", "dbnet", "opencv")
    if requested == "dbnet":
        return ("dbnet", "opencv")
    if requested == "opencv":
        return ("opencv",)
    raise ValueError(f"Unsupported detector backend: {requested}")


def classify_region_type(image: Image.Image, region: TextRegion, settings: Settings) -> str:
    if region.region_type in {"dialogue", "narration", "sfx"}:
        return region.region_type
    x1, y1, x2, y2 = region.box
    x1 = max(0, min(image.width, x1)); x2 = max(0, min(image.width, x2))
    y1 = max(0, min(image.height, y1)); y2 = max(0, min(image.height, y2))
    if x2 <= x1 or y2 <= y1:
        return "unknown"

    gray = cv2.cvtColor(np.asarray(image.convert("RGB"))[y1:y2, x1:x2], cv2.COLOR_RGB2GRAY)
    area_ratio = ((x2 - x1) * (y2 - y1)) / max(1, image.width * image.height)
    aspect = max((x2 - x1) / max(1, y2 - y1), (y2 - y1) / max(1, x2 - x1))
    texture = float(np.std(gray))
    edges = cv2.Canny(gray, 80, 180)
    edge_density = float(np.count_nonzero(edges)) / max(1, edges.size)
    confidence = 1.0 if region.confidence is None else float(region.confidence)

    if settings.detect_sfx:
        textured_art_text = region.polarity in {"mixed", "unknown"} and area_ratio >= 0.004 and texture >= 45 and edge_density >= 0.10
        large_stylized = area_ratio >= 0.018 and (aspect >= 2.8 or confidence < 0.55) and texture >= 35 and edge_density >= 0.075
        if textured_art_text or large_stylized:
            region.metadata["region_classifier"] = {
                "rule": "sfx_heuristic",
                "texture": round(texture, 2),
                "edge_density": round(edge_density, 4),
                "area_ratio": round(area_ratio, 5),
            }
            return "sfx"

    if region.polarity == "light_on_dark":
        return "narration"
    if region.polarity == "dark_on_light":
        return "dialogue"
    return "unknown"


def _run_chain(image: Image.Image, settings: Settings, requested: str) -> DetectorRun:
    reasons: list[str] = []
    for backend in _backend_chain(requested):
        detector = create_detector(backend, settings)
        try:
            regions = detector.detect(image)
            for region in regions:
                region.metadata.setdefault("detector", backend)
                if reasons:
                    region.metadata.setdefault("detector_fallbacks", list(reasons))
                region.region_type = classify_region_type(image, region, settings)
            return DetectorRun(regions, backend, reasons)
        except Exception as exc:
            reasons.append(f"{backend}: {type(exc).__name__}: {exc}")
            if backend == "opencv":
                raise RuntimeError("All detector backends failed: " + "; ".join(reasons)) from exc
    return DetectorRun([], "", reasons)


class AutoDetector:
    name = "auto"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.last_run = DetectorRun([], "", [])

    def detect(self, image: Image.Image) -> list[TextRegion]:
        self.last_run = _run_chain(image, self.settings, "auto")
        return self.last_run.regions


def detect_with_backend(image: Image.Image, settings: Settings) -> DetectorRun:
    return _run_chain(image, settings, settings.detector)


__all__ = [
    "AutoDetector", "CTDDetector", "DBNetDetector", "DetectorRun", "DetectorUnavailable",
    "OpenCVDetector", "TextDetector", "classify_region_type", "create_detector",
    "detect_with_backend", "merge_boxes",
]
