from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ..models import Settings, TextRegion
from .base import DetectorUnavailable
from .opencv import detect_polarity


class DBNetDetector:
    """OpenCV DNN DBNet adapter for user-supplied ONNX/TensorFlow DB models."""

    name = "dbnet"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._model = None

    def _model_path(self) -> Path:
        if self.settings.dbnet_model_path:
            path = Path(self.settings.dbnet_model_path).expanduser()
        else:
            root = Path(self.settings.model_cache_dir).expanduser() if self.settings.model_cache_dir else Path.home() / ".cache" / "small-things" / "auto-manga"
            candidates = [root / "models" / "dbnet" / "dbnet.onnx", root / "models" / "dbnet" / "DB_IC15_resnet18.onnx"]
            path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
        if not path.is_file():
            raise DetectorUnavailable(f"DBNet model not found at {path}; set dbnet_model_path or install it in the model cache.")
        return path

    def _load(self):
        if self._model is not None:
            return self._model
        if not hasattr(cv2, "dnn_TextDetectionModel_DB"):
            raise DetectorUnavailable("This OpenCV build does not provide dnn_TextDetectionModel_DB.")
        try:
            model = cv2.dnn_TextDetectionModel_DB(str(self._model_path()))
            size = 736 if self.settings.runtime_profile in {"auto", "balanced", "quality"} else 512
            model.setInputParams(1.0 / 255.0, (size, size), (122.67891434, 116.66876762, 104.00698793), True)
            model.setBinaryThreshold(0.3)
            model.setPolygonThreshold(max(0.3, self.settings.detector_min_confidence))
            model.setUnclipRatio(1.8)
            self._model = model
        except Exception as exc:
            raise DetectorUnavailable(f"DBNet initialization failed: {exc}") from exc
        return self._model

    def detect(self, image: Image.Image) -> list[TextRegion]:
        model = self._load()
        rgb = np.array(image.convert("RGB"))
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        try:
            polygons, confidences = model.detect(bgr)
        except Exception as exc:
            raise RuntimeError(f"DBNet inference failed: {exc}") from exc
        regions: list[TextRegion] = []
        confidences = confidences if confidences is not None else []
        for index, polygon in enumerate([] if polygons is None else polygons):
            arr = np.asarray(polygon, dtype=np.int32).reshape(-1, 2)
            x, y, w, h = cv2.boundingRect(arr)
            if w < 4 or h < 4:
                continue
            x1 = max(0, x); y1 = max(0, y); x2 = min(image.width, x + w); y2 = min(image.height, y + h)
            conf = float(confidences[index]) if index < len(confidences) else None
            regions.append(TextRegion(
                x1, y1, x2 - x1, y2 - y1,
                direction="vertical" if (y2 - y1) > (x2 - x1) * 1.15 else "horizontal",
                confidence=conf,
                polarity=detect_polarity(gray[y1:y2, x1:x2]),
                polygon=[[int(px), int(py)] for px, py in arr.tolist()],
                metadata={"detector": self.name},
            ))
        return regions
