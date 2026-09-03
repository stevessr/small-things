from __future__ import annotations

import importlib
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ..models import Settings, TextRegion
from ..model_cache import ensure_model
from ..runtime import inference_size, resolve_runtime_profile
from .base import DetectorUnavailable
from .opencv import detect_polarity


class CTDDetector:
    """Adapter for dmMaze/Ajatt-Tools comic_text_detector's TextDetector API.

    The upstream project is not a stable PyPI dependency, so this adapter deliberately
    imports it lazily. Users may install it as a package or put its package on PYTHONPATH.
    Model weights are never executed as Python; the preferred model is ONNX.
    """

    name = "ctd"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._detector = None

    def _model_path(self) -> Path:
        if self.settings.ctd_model_path:
            path = Path(self.settings.ctd_model_path).expanduser()
            if not path.is_file():
                raise DetectorUnavailable(f"CTD model not found at {path}")
            return path
        try:
            return ensure_model("ctd", self.settings)
        except Exception as exc:
            raise DetectorUnavailable(f"CTD model unavailable: {exc}") from exc

    def _load(self):
        if self._detector is not None:
            return self._detector
        module = None
        errors: list[str] = []
        for name in ("comic_text_detector.inference", "comictextdetector.inference"):
            try:
                module = importlib.import_module(name)
                break
            except Exception as exc:  # optional backend; preserve root cause for fallback logs
                errors.append(f"{name}: {exc}")
        if module is None or not hasattr(module, "TextDetector"):
            raise DetectorUnavailable(
                "CTD Python runtime is unavailable; install dmMaze/comic-text-detector or Ajatt-Tools/comic_text_detector. "
                + " | ".join(errors)
            )
        profile = resolve_runtime_profile(self.settings.runtime_profile)
        device = "cuda" if profile != "cpu" else "cpu"
        input_size = inference_size(profile)
        try:
            self._detector = module.TextDetector(
                model_path=str(self._model_path()),
                input_size=input_size,
                device=device,
                conf_thresh=self.settings.detector_min_confidence,
            )
        except Exception as exc:
            raise DetectorUnavailable(f"CTD initialization failed: {exc}") from exc
        return self._detector

    def detect(self, image: Image.Image) -> list[TextRegion]:
        detector = self._load()
        rgb = np.array(image.convert("RGB"))
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        try:
            _mask, _refined, blocks = detector(bgr)
        except Exception as exc:
            raise RuntimeError(f"CTD inference failed: {exc}") from exc
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        regions: list[TextRegion] = []
        for block in blocks or []:
            xyxy = getattr(block, "xyxy", None)
            if xyxy is None or len(xyxy) < 4:
                continue
            x1, y1, x2, y2 = map(int, xyxy[:4])
            x1 = max(0, x1); y1 = max(0, y1); x2 = min(image.width, x2); y2 = min(image.height, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            lines = getattr(block, "lines", None)
            polygon = None
            if lines is not None:
                try:
                    arr = np.asarray(lines).reshape(-1, 2)
                    polygon = [[int(x), int(y)] for x, y in arr.tolist()]
                except Exception:
                    polygon = None
            conf = getattr(block, "confidence", None)
            if conf is None:
                conf = getattr(block, "prob", None)
            direction = "vertical" if (y2 - y1) > (x2 - x1) * 1.15 else "horizontal"
            regions.append(TextRegion(
                x1, y1, x2 - x1, y2 - y1,
                direction=direction,
                confidence=float(conf) if conf is not None else None,
                polarity=detect_polarity(gray[y1:y2, x1:x2]),
                polygon=polygon,
                metadata={"detector": self.name},
            ))
        return regions
