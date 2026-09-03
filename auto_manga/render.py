from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .models import Settings, TextRegion


def _hex_color(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    if len(value) != 6:
        raise ValueError(f"Invalid color: {value}")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def build_text_mask(image: Image.Image, regions: list[TextRegion], settings: Settings) -> np.ndarray:
    rgb = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    mask = np.zeros(gray.shape, dtype=np.uint8)
    for region in regions:
        if not region.enabled:
            continue
        x1, y1, x2, y2 = region.box
        crop = gray[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        _, dark = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        ratio = float(np.count_nonzero(dark)) / max(1, dark.size)
        if ratio > 0.45:
            dark = np.where(crop < 135, 255, 0).astype(np.uint8)
        if settings.inpaint_dilate > 0:
            size = settings.inpaint_dilate * 2 + 1
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
            dark = cv2.dilate(dark, kernel, iterations=1)
        mask[y1:y2, x1:x2] = np.maximum(mask[y1:y2, x1:x2], dark)
    return mask


def erase_original_text(image: Image.Image, regions: list[TextRegion], settings: Settings) -> Image.Image:
    rgb = np.array(image.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    mask = build_text_mask(image, regions, settings)
    cleaned = cv2.inpaint(
        bgr,
        mask,
        max(1, settings.inpaint_radius),
        cv2.INPAINT_TELEA,
    )
    return Image.fromarray(cv2.cvtColor(cleaned, cv2.COLOR_BGR2RGB))


def resolve_font(settings: Settings, size: int):
    if settings.font_path:
        return ImageFont.truetype(settings.font_path, size=size)
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                pass
    return ImageFont.load_default()


def _measure(draw: ImageDraw.ImageDraw, text: str, font, stroke: int = 0) -> tuple[int, int]:
    if not text:
        return 0, 0
    box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    return box[2] - box[0], box[3] - box[1]


def normalize_layout_text(text: str) -> str:
    return " ".join(text.replace("\u3000", " ").split()) if "\n" not in text else "\n".join(
        " ".join(line.split()) for line in text.splitlines()
    ).strip()


def wrap_horizontal(text: str, draw: ImageDraw.ImageDraw, font, max_width: int, stroke: int = 0) -> list[str]:
    text = normalize_layout_text(text)
    if not text:
        return []
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            candidate = current + char
            if current and _measure(draw, candidate, font, stroke)[0] > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines


def _horizontal_layout(text: str, size: int, box_w: int, box_h: int, settings: Settings, draw):
    font = resolve_font(settings, size)
    lines = wrap_horizontal(text, draw, font, box_w, settings.stroke_width)
    if not lines:
        return True, lines, font, 0
    line_h = max(
        1,
        max(_measure(draw, line or " ", font, settings.stroke_width)[1] for line in lines),
    )
    total_h = math.ceil(line_h * len(lines) * settings.line_spacing)
    widest = max((_measure(draw, line, font, settings.stroke_width)[0] for line in lines), default=0)
    return widest <= box_w and total_h <= box_h, lines, font, line_h


def _draw_horizontal(draw, region: TextRegion, text: str, settings: Settings, fill, stroke_fill) -> None:
    margin = settings.box_margin
    box_w = max(1, region.w - margin * 2)
    box_h = max(1, region.h - margin * 2)
    chosen = None
    for size in range(settings.font_size, settings.min_font_size - 1, -2):
        ok, lines, font, line_h = _horizontal_layout(text, size, box_w, box_h, settings, draw)
        chosen = (lines, font, line_h)
        if ok:
            break
    lines, font, line_h = chosen or (
        [],
        resolve_font(settings, settings.min_font_size),
        settings.min_font_size,
    )
    total_h = line_h * len(lines) * settings.line_spacing
    y = region.y + margin + max(0, (box_h - total_h) / 2)
    for line in lines:
        width, _ = _measure(draw, line, font, settings.stroke_width)
        x = region.x + margin + max(0, (box_w - width) / 2)
        draw.text(
            (x, y),
            line,
            font=font,
            fill=fill,
            stroke_width=settings.stroke_width,
            stroke_fill=stroke_fill,
        )
        y += line_h * settings.line_spacing


def _vertical_columns(text: str, max_chars: int) -> list[str]:
    chars = [char for char in normalize_layout_text(text) if char != "\n"]
    max_chars = max(1, max_chars)
    return ["".join(chars[i : i + max_chars]) for i in range(0, len(chars), max_chars)]


def _draw_vertical(draw, region: TextRegion, text: str, settings: Settings, fill, stroke_fill) -> None:
    margin = settings.box_margin
    box_w = max(1, region.w - margin * 2)
    box_h = max(1, region.h - margin * 2)
    chosen = None
    for size in range(settings.font_size, settings.min_font_size - 1, -2):
        font = resolve_font(settings, size)
        _, char_h = _measure(draw, "国", font, settings.stroke_width)
        char_h = max(char_h, size)
        max_chars = max(1, int(box_h / (char_h * settings.line_spacing)))
        columns = _vertical_columns(text, max_chars)
        col_w = max(size, _measure(draw, "国", font, settings.stroke_width)[0])
        total_w = col_w * len(columns) * settings.line_spacing
        chosen = (size, font, char_h, col_w, columns)
        if total_w <= box_w:
            break
    if not chosen:
        return

    size, font, char_h, col_w, columns = chosen
    total_w = col_w * len(columns) * settings.line_spacing
    x = region.x + region.w - margin - col_w - max(0, (box_w - total_w) / 2)
    punctuation = set("。、，！？：；…（）()「」『』【】")

    for column in columns:
        col_height = char_h * len(column) * settings.line_spacing
        y = region.y + margin + max(0, (box_h - col_height) / 2)
        for char in column:
            char_w, _ = _measure(draw, char, font, settings.stroke_width)
            dx = max(0, (col_w - char_w) / 2)
            dy = -size * 0.08 if char in punctuation else 0
            draw.text(
                (x + dx, y + dy),
                char,
                font=font,
                fill=fill,
                stroke_width=settings.stroke_width,
                stroke_fill=stroke_fill,
            )
            y += char_h * settings.line_spacing
        x -= col_w * settings.line_spacing


def typeset_translations(image: Image.Image, regions: list[TextRegion], settings: Settings) -> Image.Image:
    output = image.convert("RGB")
    draw = ImageDraw.Draw(output)
    fill = _hex_color(settings.text_color)
    stroke_fill = _hex_color(settings.stroke_color)
    for region in regions:
        if not region.enabled:
            continue
        text = region.translation.strip() or region.source.strip()
        if not text:
            continue
        direction = settings.typeset_direction
        if direction == "auto":
            direction = region.direction if region.direction in {"horizontal", "vertical"} else (
                "vertical" if region.h > region.w * 1.2 else "horizontal"
            )
        if direction == "vertical":
            _draw_vertical(draw, region, text, settings, fill, stroke_fill)
        else:
            _draw_horizontal(draw, region, text, settings, fill, stroke_fill)
    return output


def save_image(image: Image.Image, output_path: Path, settings: Settings) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() in {".jpg", ".jpeg"}:
        image.save(output_path, quality=settings.jpeg_quality, subsampling=0)
    else:
        image.save(output_path)
