from __future__ import annotations

import unittest

import numpy as np
from PIL import Image, ImageDraw

from auto_manga.masking import build_region_glyph_mask, build_text_mask
from auto_manga.models import Settings, TextRegion
from auto_manga.render import resolve_font, wrap_horizontal
from auto_manga.typography import infer_region_style, resolve_region_style, resolve_typeset_box


class RefinedCleaningTests(unittest.TestCase):
    def test_color_aware_mask_finds_equal_luminance_colored_text(self):
        # Red and this green are close in grayscale luminance, but strongly separated by RGB channels.
        image = Image.new("RGB", (120, 90), (0, 130, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((38, 28, 48, 62), fill=(255, 0, 0))
        draw.rectangle((60, 28, 70, 62), fill=(255, 0, 0))
        region = TextRegion(20, 15, 70, 60)
        settings = Settings(mask_color_aware=True, inpaint_dilate=0, mask_auto_expand=False)
        mask = build_text_mask(image, [region], settings)
        self.assertGreater(int(np.count_nonzero(mask)), 0)
        self.assertEqual(region.metadata.get("mask_mode"), "color-aware")

    def test_polygon_guard_rejects_nearby_line_art(self):
        image = Image.new("RGB", (130, 100), "white")
        draw = ImageDraw.Draw(image)
        draw.line((18, 24, 103, 42), fill="black", width=4)
        draw.rectangle((48, 55, 58, 72), fill="black")
        draw.rectangle((68, 55, 78, 72), fill="black")
        region = TextRegion(
            10,
            10,
            105,
            80,
            polygon=[[42, 48], [84, 48], [84, 78], [42, 78]],
        )
        settings = Settings(mask_polygon_guard=True, inpaint_dilate=0, mask_auto_expand=False)
        mask = build_text_mask(image, [region], settings)
        text_pixels = int(np.count_nonzero(mask[48:80, 40:88]))
        line_pixels = int(np.count_nonzero(mask[14:45, 15:108]))
        self.assertGreater(text_pixels, 0)
        self.assertLess(line_pixels, text_pixels)

    def test_adaptive_dilation_scales_with_large_glyphs(self):
        image = Image.new("RGB", (100, 100), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((35, 35, 64, 64), fill="black")
        region = TextRegion(20, 20, 60, 60)
        settings = Settings(inpaint_dilate=1, mask_auto_expand=True, mask_max_dilate=6)
        glyph = build_region_glyph_mask(image, region, settings)
        self.assertGreater(int(np.count_nonzero(glyph)), 0)
        self.assertGreaterEqual(int(region.metadata.get("mask_dilate", 0)), 3)


class TypographyTests(unittest.TestCase):
    def test_source_style_infers_black_text_on_white_without_outline(self):
        image = Image.new("RGB", (120, 100), "white")
        draw = ImageDraw.Draw(image)
        for x in (38, 54, 70):
            draw.rectangle((x, 35, x + 8, 62), fill="black")
        region = TextRegion(25, 20, 70, 60, direction="horizontal", region_type="dialogue")
        style = infer_region_style(image, region, Settings())
        text_rgb = tuple(int(style["text_color"][i:i + 2], 16) for i in (1, 3, 5))
        bg_rgb = tuple(int(style["background_color"][i:i + 2], 16) for i in (1, 3, 5))
        self.assertLess(sum(text_rgb), 180)
        self.assertGreater(sum(bg_rgb), 600)
        self.assertGreaterEqual(style["font_size"], 10)
        self.assertEqual(style["stroke_width"], 0)

    def test_safe_typeset_box_expands_inside_balloon_but_stops_at_border(self):
        image = Image.new("RGB", (130, 105), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 10, 118, 94), outline="black", width=3)
        region = TextRegion(42, 36, 30, 22, region_type="dialogue")
        region.metadata["source_style"] = {"background_color": "#FFFFFF"}
        settings = Settings(typeset_expand_ratio=1.0, typeset_background_tolerance=20)
        box = resolve_typeset_box(image, region, settings)
        self.assertLess(box[0], region.x)
        self.assertLess(box[1], region.y)
        self.assertGreater(box[2], region.x + region.w)
        self.assertGreater(box[3], region.y + region.h)
        self.assertGreaterEqual(box[0], 12)
        self.assertGreaterEqual(box[1], 12)
        self.assertLessEqual(box[2], 116)
        self.assertLessEqual(box[3], 92)

    def test_region_type_selects_specific_font_and_manual_override_wins(self):
        settings = Settings(
            font_path="fallback.ttf",
            dialogue_font_path="dialogue.ttf",
            narration_font_path="narration.ttf",
        )
        region = TextRegion(0, 0, 50, 50, region_type="dialogue")
        self.assertEqual(resolve_region_style(region, settings)["font_path"], "dialogue.ttf")
        region.metadata["render_style"] = {"font_path": "manual.ttf", "font_size": 25, "stroke_width": 1}
        style = resolve_region_style(region, settings)
        self.assertEqual(style["font_path"], "manual.ttf")
        self.assertEqual(style["font_size"], 25)
        self.assertEqual(style["stroke_width"], 1)

    def test_word_wrapping_keeps_latin_words_together(self):
        settings = Settings(font_size=24)
        font = resolve_font(settings, 24)
        scratch = Image.new("RGB", (300, 100), "white")
        draw = ImageDraw.Draw(scratch)
        hello_box = draw.textbbox((0, 0), "hello", font=font)
        world_box = draw.textbbox((0, 0), "world", font=font)
        phrase_box = draw.textbbox((0, 0), "hello world", font=font)
        word_width = max(hello_box[2] - hello_box[0], world_box[2] - world_box[0])
        phrase_width = phrase_box[2] - phrase_box[0]
        max_width = min(phrase_width - 1, word_width + 4)
        lines = wrap_horizontal("hello world", draw, font, max_width)
        self.assertEqual(lines, ["hello", "world"])


if __name__ == "__main__":
    unittest.main()
