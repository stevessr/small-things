from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol
import numpy as np
from PIL import Image


class InpainterUnavailable(RuntimeError):
    pass


class Inpainter(Protocol):
    name: str
    def inpaint(self, image: Image.Image, mask: np.ndarray) -> Image.Image:
        ...


@dataclass
class InpaintRun:
    image: Image.Image
    backend: str
    fallback_reasons: list[str] = field(default_factory=list)
