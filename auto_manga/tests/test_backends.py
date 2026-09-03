from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image, ImageDraw

from auto_manga.detectors import classify_region_type, detect_with_backend
from auto_manga.inpainters import inpaint_with_backend
from auto_manga.model_cache import ModelSpec, verify_model
from auto_manga.models import Settings, TextRegion
from auto_manga.providers import translate_regions


class BackendSafetyTests(unittest.TestCase):
    def test_sfx_classifier_marks_large_textured_region(self):
        image = Image.new("RGB", (120, 120), "white")
        draw = ImageDraw.Draw(image)
        for y in range(20, 100, 8):
            for x in range(20, 100, 8):
                draw.rectangle((x, y, x + 4, y + 4), fill="black" if (x + y) % 16 == 0 else "gray")
        region = TextRegion(20, 20, 80, 80, confidence=0.4, polarity="mixed", region_type="unknown")
        self.assertEqual(classify_region_type(image, region, Settings(detect_sfx=True)), "sfx")

    def test_detect_sfx_false_keeps_conservative_unknown(self):
        image = Image.new("RGB", (120, 120), "white")
        draw = ImageDraw.Draw(image)
        for y in range(20, 100, 8):
            draw.line((20, y, 100, y), fill="black", width=2)
        region = TextRegion(20, 20, 80, 80, confidence=0.3, polarity="mixed")
        self.assertEqual(classify_region_type(image, region, Settings(detect_sfx=False)), "unknown")

    def test_explicit_dbnet_falls_back_to_opencv(self):
        image = Image.new("RGB", (80, 80), "white")
        dbnet = Mock(); dbnet.detect.side_effect = RuntimeError("dbnet model missing")
        opencv = Mock(); opencv.detect.return_value = [TextRegion(10, 10, 20, 20)]
        def factory(name, _settings):
            return {"dbnet": dbnet, "opencv": opencv}[name]
        with patch("auto_manga.detectors.create_detector", side_effect=factory):
            run = detect_with_backend(image, Settings(detector="dbnet"))
        self.assertEqual(run.backend, "opencv")
        self.assertEqual(len(run.fallback_reasons), 1)

    def test_lama_missing_model_falls_back(self):
        image = Image.new("RGB", (40, 40), "white")
        mask = np.zeros((40, 40), dtype=np.uint8)
        lama = Mock(); lama.inpaint.side_effect = RuntimeError("LaMa model not found")
        opencv = Mock(); opencv.inpaint.return_value = image
        def factory(name, _settings):
            return {"lama": lama, "opencv": opencv}[name]
        with patch("auto_manga.inpainters.create_inpainter", side_effect=factory):
            run = inpaint_with_backend(image, mask, Settings(inpainter="lama"))
        self.assertEqual(run.backend, "opencv")
        self.assertTrue(any("model not found" in reason for reason in run.fallback_reasons))

    def test_lama_inference_exception_falls_back(self):
        image = Image.new("RGB", (40, 40), "white")
        mask = np.zeros((40, 40), dtype=np.uint8)
        lama = Mock(); lama.inpaint.side_effect = RuntimeError("inference exploded")
        opencv = Mock(); opencv.inpaint.return_value = image
        def factory(name, _settings):
            return {"lama": lama, "opencv": opencv}[name]
        with patch("auto_manga.inpainters.create_inpainter", side_effect=factory):
            run = inpaint_with_backend(image, mask, Settings(inpainter="auto"))
        self.assertEqual(run.backend, "opencv")
        self.assertTrue(any("inference exploded" in reason for reason in run.fallback_reasons))

    def test_preserved_sfx_is_not_translated(self):
        region = TextRegion(1, 1, 20, 20, source="ドン", region_type="sfx")
        settings = Settings(translation_provider="none", preserve_sfx=True, translate_sfx=False)
        with tempfile.TemporaryDirectory() as td:
            translate_regions([region], settings, Path(td))
        self.assertEqual(region.translation, "")

    def test_model_checksum_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "model.bin"
            path.write_bytes(b"not-the-model")
            spec = ModelSpec(key="test", relative_path="model.bin", url="https://example.invalid/model.bin", sha256="0" * 64, size=None)
            with self.assertRaisesRegex(RuntimeError, "SHA256 mismatch"):
                verify_model(path, spec)


if __name__ == "__main__":
    unittest.main()
