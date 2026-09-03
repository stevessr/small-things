from __future__ import annotations

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


class AutoDetector:
    name = "auto"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.last_run = DetectorRun([], "", [])

    def detect(self, image: Image.Image) -> list[TextRegion]:
        reasons: list[str] = []
        for backend in ("ctd", "dbnet", "opencv"):
            detector = create_detector(backend, self.settings)
            try:
                regions = detector.detect(image)
                self.last_run = DetectorRun(regions, backend, reasons)
                for region in regions:
                    region.metadata.setdefault("detector", backend)
                    if reasons:
                        region.metadata.setdefault("detector_fallbacks", list(reasons))
                return regions
            except Exception as exc:
                reasons.append(f"{backend}: {type(exc).__name__}: {exc}")
                if backend == "opencv":
                    raise
        self.last_run = DetectorRun([], "", reasons)
        return []


def detect_with_backend(image: Image.Image, settings: Settings) -> DetectorRun:
    detector = create_detector(settings.detector, settings)
    regions = detector.detect(image)
    if isinstance(detector, AutoDetector):
        return detector.last_run
    return DetectorRun(regions, getattr(detector, "name", settings.detector), [])


__all__ = [
    "AutoDetector", "CTDDetector", "DBNetDetector", "DetectorRun", "DetectorUnavailable",
    "OpenCVDetector", "TextDetector", "create_detector", "detect_with_backend", "merge_boxes",
]
