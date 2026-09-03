from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from PIL import Image

from ..models import TextRegion


class DetectorUnavailable(RuntimeError):
    """Raised when a detector backend cannot be loaded on this machine."""


class TextDetector(Protocol):
    name: str

    def detect(self, image: Image.Image) -> list[TextRegion]:
        ...


@dataclass
class DetectorRun:
    regions: list[TextRegion]
    backend: str
    fallback_reasons: list[str] = field(default_factory=list)
