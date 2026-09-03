from __future__ import annotations
import os
from pathlib import Path
import numpy as np
from PIL import Image
from ..model_cache import ensure_model
from ..models import Settings
from ..runtime import resolve_runtime_profile
from .base import InpainterUnavailable


class LaMaInpainter:
    name = "lama"
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model = None

    def _model_path(self) -> Path:
        if self.settings.lama_model_path:
            path = Path(self.settings.lama_model_path).expanduser()
            if not path.is_file():
                raise InpainterUnavailable(f"LaMa model not found at {path}")
            return path
        try:
            return ensure_model("lama", self.settings)
        except Exception as exc:
            raise InpainterUnavailable(f"LaMa model unavailable: {exc}") from exc

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            import torch
            from simple_lama_inpainting import SimpleLama
        except Exception as exc:
            raise InpainterUnavailable("simple-lama-inpainting is not installed") from exc
        profile = resolve_runtime_profile(self.settings.runtime_profile)
        if profile == "cpu":
            device = torch.device("cpu")
        else:
            if not torch.cuda.is_available():
                raise InpainterUnavailable("CUDA requested by runtime profile but is unavailable")
            device = torch.device("cuda")
        model_path = self._model_path()
        # Force the package to use our SHA-verified cache path; do not allow its own unchecked downloader.
        previous = os.environ.get("LAMA_MODEL")
        os.environ["LAMA_MODEL"] = str(model_path)
        try:
            self._model = SimpleLama(device=device)
        except Exception as exc:
            raise InpainterUnavailable(f"LaMa initialization failed: {exc}") from exc
        finally:
            if previous is None:
                os.environ.pop("LAMA_MODEL", None)
            else:
                os.environ["LAMA_MODEL"] = previous
        return self._model

    def inpaint(self, image: Image.Image, mask: np.ndarray) -> Image.Image:
        model = self._load()
        mask_image = Image.fromarray(mask.astype(np.uint8), mode="L")
        try:
            return model(image.convert("RGB"), mask_image).convert("RGB")
        except Exception as exc:
            raise RuntimeError(f"LaMa inference failed: {exc}") from exc
