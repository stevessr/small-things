from __future__ import annotations
import cv2
import numpy as np
from PIL import Image
from ..models import Settings


class OpenCVInpainter:
    name = "opencv"
    def __init__(self, settings: Settings):
        self.settings = settings
    def inpaint(self, image: Image.Image, mask: np.ndarray) -> Image.Image:
        rgb = np.array(image.convert("RGB"))
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        cleaned = cv2.inpaint(bgr, mask.astype(np.uint8), max(1, self.settings.inpaint_radius), cv2.INPAINT_TELEA)
        return Image.fromarray(cv2.cvtColor(cleaned, cv2.COLOR_BGR2RGB))
