from __future__ import annotations
import numpy as np
from PIL import Image
from ..models import Settings
from .base import InpaintRun, Inpainter, InpainterUnavailable
from .lama import LaMaInpainter
from .opencv import OpenCVInpainter


def create_inpainter(name: str, settings: Settings) -> Inpainter:
    name = name.lower().strip()
    if name == "opencv": return OpenCVInpainter(settings)
    if name == "lama": return LaMaInpainter(settings)
    if name == "auto": return AutoInpainter(settings)
    raise ValueError(f"Unsupported inpainter backend: {name}")


class AutoInpainter:
    name = "auto"
    def __init__(self, settings: Settings):
        self.settings = settings
        self.last_run: InpaintRun | None = None
    def inpaint(self, image: Image.Image, mask: np.ndarray) -> Image.Image:
        reasons: list[str] = []
        for backend in ("lama", "opencv"):
            try:
                result = create_inpainter(backend, self.settings).inpaint(image, mask)
                self.last_run = InpaintRun(result, backend, reasons)
                return result
            except Exception as exc:
                reasons.append(f"{backend}: {type(exc).__name__}: {exc}")
                if backend == "opencv": raise
        raise RuntimeError("No inpainter backend succeeded")


def inpaint_with_backend(image: Image.Image, mask: np.ndarray, settings: Settings) -> InpaintRun:
    inpainter = create_inpainter(settings.inpainter, settings)
    result = inpainter.inpaint(image, mask)
    if isinstance(inpainter, AutoInpainter) and inpainter.last_run is not None:
        return inpainter.last_run
    return InpaintRun(result, getattr(inpainter, "name", settings.inpainter), [])


__all__ = ["AutoInpainter", "InpaintRun", "Inpainter", "InpainterUnavailable", "LaMaInpainter", "OpenCVInpainter", "create_inpainter", "inpaint_with_backend"]
