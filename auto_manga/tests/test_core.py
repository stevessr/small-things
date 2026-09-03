from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from auto_manga.core import (
    Settings, TextRegion, PageJob, build_text_mask, detect_text_regions,
    discover_pages, load_glossary, load_project, load_translation_memory,
    merge_boxes, natural_sort_key, page_fingerprint, page_output_paths,
    save_project, save_translation_memory, typeset_translations
)


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

    def test_detect_text_regions_synthetic(self):
        img = Image.new("RGB", (500, 700), "white")
        d = ImageDraw.Draw(img)
        for y in range(120, 320, 34):
            d.rectangle((310, y, 326, y + 22), fill="black")
            d.rectangle((335, y + 4, 350, y + 25), fill="black")
        s = Settings()
        s.detect_min_area_ratio = 0.00001
        s.detect_max_area_ratio = 0.3
        regions = detect_text_regions(img, s)
        self.assertGreaterEqual(len(regions), 1)
        self.assertTrue(any(r.x > 250 and r.y < 350 for r in regions))

    def test_build_text_mask_has_text_pixels(self):
        img = Image.new("RGB", (100, 100), "white")
        d = ImageDraw.Draw(img)
        d.rectangle((35, 35, 55, 55), fill="black")
        mask = build_text_mask(img, [TextRegion(25, 25, 45, 45)], Settings())
        self.assertGreater(int(np.count_nonzero(mask)), 0)
        self.assertEqual(mask.shape, (100, 100))

    def test_translation_memory_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save_translation_memory(root, {"abc": "中文"})
            self.assertEqual(load_translation_memory(root), {"abc": "中文"})

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

    def test_project_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "1.png"
            Image.new("RGB", (100, 100)).save(src)
            job = PageJob(src, Path("1.png"))
            project = root / "1.manga.json"
            regions = [TextRegion(1, 2, 30, 40, source="こんにちは", translation="你好", direction="vertical")]
            save_project(project, job, Settings(), regions, "finger")
            data, loaded = load_project(project)
            self.assertEqual(data["fingerprint"], "finger")
            self.assertEqual(loaded[0].translation, "你好")
            self.assertEqual(loaded[0].box, (1, 2, 31, 42))

    def test_fingerprint_does_not_include_api_secret(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "1.png"
            Image.new("RGB", (10, 10)).save(src)
            job = PageJob(src, Path("1.png"))
            a = Settings()
            b = Settings()
            a.translation_api_key = "secret-a"
            b.translation_api_key = "secret-b"
            a.vision_api_key = "vision-a"
            b.vision_api_key = "vision-b"
            self.assertEqual(page_fingerprint(job, a), page_fingerprint(job, b))

    def test_typeset_horizontal_and_vertical(self):
        img = Image.new("RGB", (400, 400), "white")
        regions = [
            TextRegion(20, 20, 170, 120, translation="这是横排文本", direction="horizontal"),
            TextRegion(260, 40, 80, 280, translation="这是竖排文本", direction="vertical"),
        ]
        out = typeset_translations(img, regions, Settings())
        self.assertEqual(out.size, img.size)
        self.assertNotEqual(np.asarray(out).sum(), np.asarray(img).sum())


if __name__ == "__main__":
    unittest.main()
