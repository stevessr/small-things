"""Compatibility facade for manga text detection backends."""
from __future__ import annotations

from PIL import Image

from .detectors import (
    AutoDetector, CTDDetector, DBNetDetector, DetectorRun, DetectorUnavailable,
    OpenCVDetector, TextDetector, create_detector, detect_with_backend, merge_boxes,
)
from .models import Settings, TextRegion


def detect_text_regions(image: Image.Image, settings: Settings) -> list[TextRegion]:
    return detect_with_backend(image, settings).regions


__all__ = [
    "AutoDetector", "CTDDetector", "DBNetDetector", "DetectorRun", "DetectorUnavailable",
    "OpenCVDetector", "TextDetector", "create_detector", "detect_text_regions",
    "detect_with_backend", "merge_boxes",
]
