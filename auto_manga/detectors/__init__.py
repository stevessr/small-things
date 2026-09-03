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


def _backend_chain(requested: str) -> tuple[str, ...]:
    requested = requested.lower().strip()
    if requested == "auto":
        return ("ctd", "dbnet", "opencv")
    if requested == "ctd":
        return ("ctd", "dbnet", "opencv")
    if requested == "dbnet":
        return ("dbnet", "opencv")
    if requested == "opencv":
        return ("opencv",)
    raise ValueError(f"Unsupported detector backend: {requested}")


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
    # Explicit model backends retain batch-safe fallbacks too.
    return _run_chain(image, settings, settings.detector)


__all__ = [
    "AutoDetector", "CTDDetector", "DBNetDetector", "DetectorRun", "DetectorUnavailable",
    "OpenCVDetector", "TextDetector", "create_detector", "detect_with_backend", "merge_boxes",
]
