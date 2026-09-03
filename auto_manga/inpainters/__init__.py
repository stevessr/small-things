from __future__ import annotations

import numpy as np
from PIL import Image

from ..models import Settings
from .base import InpaintRun, Inpainter, InpainterUnavailable
from .lama import LaMaInpainter
from .opencv import OpenCVInpainter


def create_inpainter(name: str, settings: Settings) -> Inpainter:
    name = name.lower().strip()
    if name == "opencv":
        return OpenCVInpainter(settings)
    if name == "lama":
        return LaMaInpainter(settings)
    if name == "auto":
        return AutoInpainter(settings)
    raise ValueError(f"Unsupported inpainter backend: {name}")


def _backend_chain(requested: str) -> tuple[str, ...]:
    requested = requested.lower().strip()
    if requested in {"auto", "lama"}:
        return ("lama", "opencv")
    if requested == "opencv":
        return ("opencv",)
    raise ValueError(f"Unsupported inpainter backend: {requested}")


def _run_chain(image: Image.Image, mask: np.ndarray, settings: Settings, requested: str) -> InpaintRun:
    reasons: list[str] = []
    for backend in _backend_chain(requested):
        try:
            result = create_inpainter(backend, settings).inpaint(image, mask)
            return InpaintRun(result, backend, reasons)
        except Exception as exc:
            reasons.append(f"{backend}: {type(exc).__name__}: {exc}")
            if backend == "opencv":
                raise RuntimeError("All inpainter backends failed: " + "; ".join(reasons)) from exc
    raise RuntimeError("No inpainter backend succeeded")


class AutoInpainter:
    name = "auto"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.last_run: InpaintRun | None = None

    def inpaint(self, image: Image.Image, mask: np.ndarray) -> Image.Image:
        self.last_run = _run_chain(image, mask, self.settings, "auto")
        return self.last_run.image


def inpaint_with_backend(image: Image.Image, mask: np.ndarray, settings: Settings) -> InpaintRun:
    # Explicit LaMa also falls back to OpenCV instead of terminating a batch.
    return _run_chain(image, mask, settings, settings.inpainter)


__all__ = [
    "AutoInpainter", "InpaintRun", "Inpainter", "InpainterUnavailable", "LaMaInpainter",
    "OpenCVInpainter", "create_inpainter", "inpaint_with_backend",
]
