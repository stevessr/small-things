from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image, ImageDraw

from auto_manga.core import (
    DetectorRun,
    InpaintRun,
    PageJob,
    Settings,
    TextRegion,
    build_text_mask,
    detect_text_regions,
    discover_pages,
    evaluate_page_quality,
    inpaint_with_backend,
    load_glossary,
    load_project,
    load_translation_memory,
    merge_boxes,
    migrate_project,
    natural_sort_key,
    page_fingerprint,
    page_output_paths,
    process_page,
    save_project,
    save_translation_memory,
    translation_memory_key,
    typeset_translations,
)
from auto_manga.detectors import detect_with_backend


class CoreTests(unittest.TestCase):
    def test_natural_sort(self):
        values = ["10.png", "2.png", "1.png"]
        self.assertEqual(sorted(values, key=natural_sort_key), ["1.png", "2.png", "10.png"])

    def test_discover_pages_excludes_generated_and_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            Image.new("RGB", (30, 30), "white").save(root / "1.png")
            Image.new("RGB", (30, 30), "white").save(root / "2.translated.png")
            out = root / "manga-output"
            out.mkdir()
            Image.new("RGB", (30, 30), "white").save(out / "3.png")
            jobs = discover_pages(root, recursive=True, output_dir=out)
            self.assertEqual([j.relative.name for j in jobs], ["1.png"])

    def test_discover_recursive_keeps_relative_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "ch1").mkdir()
            Image.new("RGB", (10, 10)).save(root / "ch1" / "001.jpg")
            jobs = discover_pages(root, recursive=True)
            self.assertEqual(str(jobs[0].relative), str(Path("ch1") / "001.jpg"))

    def test_merge_overlapping_boxes(self):
        merged = merge_boxes([(0, 0, 20, 30), (4, 5, 18, 28), (100, 100, 10, 10)])
        self.assertEqual(len(merged), 2)
        self.assertTrue(any(b[0] == 0 and b[1] == 0 for b in merged))

    def test_detect_text_regions_synthetic_opencv(self):
        img = Image.new("RGB", (500, 700), "white")
        draw = ImageDraw.Draw(img)
        for y in range(120, 320, 34):
            draw.rectangle((310, y, 326, y + 22), fill="black")
            draw.rectangle((335, y + 4, 350, y + 25), fill="black")
        settings = Settings(detector="opencv")
        settings.detect_min_area_ratio = 0.00001
        settings.detect_max_area_ratio = 0.3
        regions = detect_text_regions(img, settings)
        self.assertGreaterEqual(len(regions), 1)
        self.assertTrue(any(r.x > 250 and r.y < 350 for r in regions))

    def test_detector_auto_falls_back_to_opencv(self):
        image = Image.new("RGB", (100, 100), "white")
        region = TextRegion(10, 10, 30, 30)
        ctd = Mock(); ctd.detect.side_effect = RuntimeError("ctd unavailable")
        dbnet = Mock(); dbnet.detect.side_effect = RuntimeError("dbnet unavailable")
        opencv = Mock(); opencv.detect.return_value = [region]
        def factory(name, _settings):
            return {"ctd": ctd, "dbnet": dbnet, "opencv": opencv}[name]
        with patch("auto_manga.detectors.create_detector", side_effect=factory):
            run = detect_with_backend(image, Settings(detector="auto"))
        self.assertEqual(run.backend, "opencv")
        self.assertEqual(len(run.fallback_reasons), 2)
        self.assertEqual(run.regions[0].metadata["detector"], "opencv")

    def test_explicit_ctd_still_falls_back(self):
        image = Image.new("RGB", (100, 100), "white")
        ctd = Mock(); ctd.detect.side_effect = RuntimeError("missing")
        dbnet = Mock(); dbnet.detect.return_value = [TextRegion(1, 1, 20, 20)]
        def factory(name, _settings):
            return {"ctd": ctd, "dbnet": dbnet}[name]
        with patch("auto_manga.detectors.create_detector", side_effect=factory):
            run = detect_with_backend(image, Settings(detector="ctd"))
        self.assertEqual(run.backend, "dbnet")
        self.assertEqual(len(run.fallback_reasons), 1)

    def test_build_text_mask_white_background_black_text(self):
        img = Image.new("RGB", (120, 120), "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle((40, 45, 50, 70), fill="black")
        draw.rectangle((60, 45, 70, 70), fill="black")
        region = TextRegion(25, 25, 65, 65)
        mask = build_text_mask(img, [region], Settings())
        count = int(np.count_nonzero(mask))
        self.assertGreater(count, 0)
        self.assertLess(count, region.w * region.h * 0.7)

    def test_build_text_mask_black_background_white_text(self):
        img = Image.new("RGB", (120, 120), "black")
        draw = ImageDraw.Draw(img)
        draw.rectangle((40, 45, 50, 70), fill="white")
        draw.rectangle((60, 45, 70, 70), fill="white")
        region = TextRegion(25, 25, 65, 65)
        mask = build_text_mask(img, [region], Settings())
        self.assertGreater(int(np.count_nonzero(mask)), 0)
        self.assertIn(region.polarity, {"light_on_dark", "mixed"})

    def test_glyph_mask_does_not_wipe_entire_bbox_with_crossing_line(self):
        img = Image.new("RGB", (160, 120), "white")
        draw = ImageDraw.Draw(img)
        draw.line((15, 60, 145, 60), fill="black", width=2)
        for x in (55, 75, 95):
            draw.rectangle((x, 40, x + 8, 52), fill="black")
        region = TextRegion(20, 25, 120, 70)
        mask = build_text_mask(img, [region], Settings())
        fill = np.count_nonzero(mask[25:95, 20:140]) / (120 * 70)
        self.assertGreater(fill, 0)
        self.assertLess(fill, 0.5)

    def test_sfx_is_preserved_from_mask(self):
        img = Image.new("RGB", (100, 100), "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle((30, 30, 60, 60), fill="black")
        region = TextRegion(20, 20, 60, 60, region_type="sfx")
        settings = Settings(preserve_sfx=True, translate_sfx=False)
        mask = build_text_mask(img, [region], settings)
        self.assertEqual(int(np.count_nonzero(mask)), 0)
        self.assertEqual(region.metadata.get("inpaint_skipped"), "preserve_sfx")

    def test_explicit_lama_falls_back_to_opencv(self):
        image = Image.new("RGB", (30, 30), "white")
        mask = np.zeros((30, 30), dtype=np.uint8)
        lama = Mock(); lama.inpaint.side_effect = RuntimeError("CUDA out of memory")
        opencv = Mock(); opencv.inpaint.return_value = image
        def factory(name, _settings):
            return {"lama": lama, "opencv": opencv}[name]
        with patch("auto_manga.inpainters.create_inpainter", side_effect=factory):
            run = inpaint_with_backend(image, mask, Settings(inpainter="lama"))
        self.assertEqual(run.backend, "opencv")
        self.assertTrue(any("CUDA out of memory" in reason for reason in run.fallback_reasons))

    def test_lama_success_does_not_fallback(self):
        image = Image.new("RGB", (30, 30), "white")
        mask = np.zeros((30, 30), dtype=np.uint8)
        lama = Mock(); lama.inpaint.return_value = image
        with patch("auto_manga.inpainters.create_inpainter", return_value=lama):
            run = inpaint_with_backend(image, mask, Settings(inpainter="lama"))
        self.assertEqual(run.backend, "lama")
        self.assertEqual(run.fallback_reasons, [])

    def test_translation_memory_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save_translation_memory(root, {"abc": "中文"})
            self.assertEqual(load_translation_memory(root), {"abc": "中文"})

    def test_translation_memory_key_changes_with_model_and_glossary(self):
        base = translation_memory_key("こんにちは", "zh-CN", "openai_compatible", "m1", "g1")
        self.assertNotEqual(base, translation_memory_key("こんにちは", "zh-CN", "openai_compatible", "m2", "g1"))
        self.assertNotEqual(base, translation_memory_key("こんにちは", "zh-CN", "openai_compatible", "m1", "g2"))

    def test_glossary_json_and_text(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            j = root / "g.json"
            j.write_text(json.dumps({"A": "甲"}, ensure_ascii=False), "utf-8")
            self.assertEqual(load_glossary(str(j))["A"], "甲")
            t = root / "g.txt"
            t.write_text("B=乙\nC\t丙\n", "utf-8")
            self.assertEqual(load_glossary(str(t)), {"B": "乙", "C": "丙"})

    def test_output_paths_preserve_subfolders(self):
        job = PageJob(Path("/tmp/x/ch/001.png"), Path("ch/001.png"))
        out, project = page_output_paths(job, Path("/tmp/out"), Settings())
        self.assertEqual(out, Path("/tmp/out/ch/001.translated.png"))
        self.assertEqual(project, Path("/tmp/out/ch/001.manga.json"))

    def test_project_roundtrip_schema_v2(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "1.png"
            Image.new("RGB", (100, 100)).save(src)
            job = PageJob(src, Path("1.png"))
            project = root / "1.manga.json"
            regions = [TextRegion(1, 2, 30, 40, source="こんにちは", translation="你好", direction="vertical", region_type="dialogue")]
            save_project(project, job, Settings(), regions, "finger")
            data, loaded = load_project(project)
            self.assertEqual(data["schema_version"], 2)
            self.assertEqual(data["fingerprint"], "finger")
            self.assertEqual(loaded[0].translation, "你好")
            self.assertEqual(loaded[0].region_type, "dialogue")

    def test_project_migration_v1_to_v2(self):
        migrated = migrate_project({"version": 1, "regions": [{"x": 1, "y": 2, "w": 3, "h": 4, "source": "a"}]})
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["regions"][0]["region_type"], "unknown")
        self.assertIn("quality", migrated)

    def test_future_project_schema_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "newer than supported"):
            migrate_project({"schema_version": 999, "regions": []})

    def test_fingerprint_does_not_include_api_secret(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "1.png"
            Image.new("RGB", (10, 10)).save(src)
            job = PageJob(src, Path("1.png"))
            a = Settings(); b = Settings()
            a.translation_api_key = "secret-a"; b.translation_api_key = "secret-b"
            a.vision_api_key = "vision-a"; b.vision_api_key = "vision-b"
            self.assertEqual(page_fingerprint(job, a), page_fingerprint(job, b))

    def test_typeset_horizontal_and_vertical(self):
        img = Image.new("RGB", (400, 400), "white")
        regions = [TextRegion(20, 20, 170, 120, translation="这是横排文本", direction="horizontal"), TextRegion(260, 40, 80, 280, translation="这是竖排文本", direction="vertical")]
        out = typeset_translations(img, regions, Settings())
        self.assertEqual(out.size, img.size)
        self.assertNotEqual(np.asarray(out).sum(), np.asarray(img).sum())

    def test_quality_flags_low_confidence_and_empty_ocr(self):
        settings = Settings(translation_provider="none")
        region = TextRegion(20, 20, 100, 80, confidence=0.1)
        quality = evaluate_page_quality((300, 300), [region], settings)
        codes = {issue["code"] for issue in quality["issues"]}
        self.assertIn("detector_low_confidence", codes)
        self.assertIn("ocr_empty", codes)
        self.assertTrue(quality["needs_review"])

    def test_quality_flags_translation_empty(self):
        settings = Settings()
        region = TextRegion(20, 20, 140, 100, source="こんにちは", confidence=0.9)
        quality = evaluate_page_quality((400, 400), [region], settings)
        self.assertIn("translation_empty", {item["code"] for item in quality["issues"]})

    def test_quality_flags_typeset_overflow(self):
        settings = Settings(font_size=42, min_font_size=30)
        region = TextRegion(20, 20, 45, 30, source="長い原文です", translation="这是非常非常非常非常长的译文，无法塞入极小的框", confidence=0.9, direction="horizontal")
        quality = evaluate_page_quality((400, 400), [region], settings)
        self.assertIn("typeset_overflow", {item["code"] for item in quality["issues"]})

    def test_normal_quality_page_does_not_need_review(self):
        settings = Settings()
        region = TextRegion(30, 30, 220, 140, source="こんにちは", translation="你好", confidence=0.95, direction="horizontal")
        quality = evaluate_page_quality((600, 600), [region], settings)
        self.assertFalse(quality["needs_review"])
        self.assertGreaterEqual(quality["score"], 0.9)


class IncrementalPipelineTests(unittest.TestCase):
    def _initial_project(self, root: Path) -> tuple[PageJob, Path, Settings]:
        src = root / "001.png"
        Image.new("RGB", (240, 240), "white").save(src)
        job = PageJob(src, Path("001.png"))
        output = root / "out"
        settings = Settings(detector="opencv", inpainter="opencv")
        def fake_ocr(_image, regions, _settings, _progress=None):
            for region in regions:
                region.source = "こんにちは"
        def fake_translate(regions, _settings, _output, _progress=None):
            for region in regions:
                region.translation = "你好"
        region = TextRegion(40, 40, 120, 100, confidence=0.95, region_type="dialogue")
        detector_run = DetectorRun([region], "opencv", [])
        clean_run = InpaintRun(Image.new("RGB", (240, 240), "white"), "opencv", [])
        with patch("auto_manga.pipeline.detect_with_backend", return_value=detector_run), patch("auto_manga.pipeline.ocr_regions", side_effect=fake_ocr), patch("auto_manga.pipeline.translate_regions", side_effect=fake_translate), patch("auto_manga.pipeline.erase_original_text_with_report", return_value=clean_run):
            process_page(job, output, settings)
        return job, output, settings

    def test_same_project_rerun_skips_expensive_stages(self):
        with tempfile.TemporaryDirectory() as td:
            job, output, settings = self._initial_project(Path(td))
            with patch("auto_manga.pipeline.detect_with_backend") as detect, patch("auto_manga.pipeline.ocr_regions") as ocr, patch("auto_manga.pipeline.translate_regions") as translate, patch("auto_manga.pipeline.erase_original_text_with_report") as inpaint:
                process_page(job, output, settings)
            self.assertEqual(job.status, "skipped")
            detect.assert_not_called(); ocr.assert_not_called(); translate.assert_not_called(); inpaint.assert_not_called()

    def test_translation_edit_only_rerenders(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            job, output, settings = self._initial_project(root)
            _out, project = page_output_paths(job, output, settings)
            data = json.loads(project.read_text("utf-8"))
            data["regions"][0]["translation"] = "手工译文"
            project.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
            with patch("auto_manga.pipeline.ocr_regions") as ocr, patch("auto_manga.pipeline.translate_regions") as translate, patch("auto_manga.pipeline.erase_original_text_with_report") as inpaint:
                process_page(job, output, settings)
            ocr.assert_not_called(); translate.assert_not_called(); inpaint.assert_not_called()
            _, regions = load_project(project)
            self.assertEqual(regions[0].translation, "手工译文")

    def test_style_edit_does_not_retranslate(self):
        with tempfile.TemporaryDirectory() as td:
            job, output, settings = self._initial_project(Path(td))
            settings.font_size += 4
            with patch("auto_manga.pipeline.ocr_regions") as ocr, patch("auto_manga.pipeline.translate_regions") as translate, patch("auto_manga.pipeline.erase_original_text_with_report") as inpaint:
                process_page(job, output, settings)
            ocr.assert_not_called(); translate.assert_not_called(); inpaint.assert_not_called()

    def test_bbox_edit_only_reinpaints_and_renders(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            job, output, settings = self._initial_project(root)
            _out, project = page_output_paths(job, output, settings)
            data = json.loads(project.read_text("utf-8"))
            data["regions"][0]["x"] += 5
            project.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
            clean_run = InpaintRun(Image.new("RGB", (240, 240), "white"), "opencv", [])
            with patch("auto_manga.pipeline.ocr_regions") as ocr, patch("auto_manga.pipeline.translate_regions") as translate, patch("auto_manga.pipeline.erase_original_text_with_report", return_value=clean_run) as inpaint:
                process_page(job, output, settings)
            ocr.assert_not_called(); translate.assert_not_called(); inpaint.assert_called_once()


if __name__ == "__main__":
    unittest.main()
