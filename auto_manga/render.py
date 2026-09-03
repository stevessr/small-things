from __future__ import annotations

import math
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .inpainters import InpaintRun, inpaint_with_backend
from .masking import build_text_mask
from .models import Settings, TextRegion
from .typography import infer_region_style, resolve_region_style, resolve_typeset_box, validate_font_path


def _hex_color(value: str) -> tuple[int, int, int]:
    clean = value.strip().lstrip("#")
    if len(clean) == 3:
        clean = "".join(char * 2 for char in clean)
    if len(clean) != 6:
        raise ValueError(f"Invalid color: {value}")
    return tuple(int(clean[index:index + 2], 16) for index in (0, 2, 4))


def erase_original_text_with_report(
    image: Image.Image,
    regions: list[TextRegion],
    settings: Settings,
) -> InpaintRun:
    if settings.match_source_style:
        for region in regions:
            if not region.enabled:
                continue
            if settings.preserve_sfx and region.region_type == "sfx" and not settings.translate_sfx:
                continue
            try:
                infer_region_style(image, region, settings)
            except Exception as exc:
                # Style matching is an enhancement; failure must never block safe cleaning.
                region.metadata["style_inference_error"] = f"{type(exc).__name__}: {exc}"

    mask = build_text_mask(image, regions, settings)
    if not np.any(mask):
        return InpaintRun(image.convert("RGB"), "none", [])
    run = inpaint_with_backend(image, mask, settings)
    for region in regions:
        if not region.enabled or (
            settings.preserve_sfx and region.region_type == "sfx" and not settings.translate_sfx
        ):
            continue
        region.metadata["inpainter"] = run.backend
        if run.fallback_reasons:
            region.metadata["inpaint_fallbacks"] = list(run.fallback_reasons)
    return run


def erase_original_text(image: Image.Image, regions: list[TextRegion], settings: Settings) -> Image.Image:
    return erase_original_text_with_report(image, regions, settings).image


def resolve_font(settings: Settings, size: int, font_path: str = ""):
    requested = validate_font_path(font_path or settings.font_path)
    if requested:
        try:
            return ImageFont.truetype(requested, size=size)
        except OSError:
            pass
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
    if "\n" not in text:
        return " ".join(text.replace("\u3000", " ").split())
    return "\n".join(" ".join(line.replace("\u3000", " ").split()) for line in text.splitlines()).strip()


def _wrap_long_token(token: str, draw, font, max_width: int, stroke: int) -> list[str]:
    parts: list[str] = []
    current = ""
    for char in token:
        candidate = current + char
        if current and _measure(draw, candidate, font, stroke)[0] > max_width:
            parts.append(current)
            current = char
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def wrap_horizontal(text: str, draw, font, max_width: int, stroke: int = 0) -> list[str]:
    text = normalize_layout_text(text)
    if not text:
        return []
    lines: list[str] = []
    token_pattern = re.compile(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*|\s+|.", re.DOTALL)
    for paragraph in text.splitlines() or [text]:
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for token in token_pattern.findall(paragraph):
            if token.isspace():
                if current and not current.endswith(" "):
                    current += " "
                continue
            candidate = current + token
            if not current or _measure(draw, candidate, font, stroke)[0] <= max_width:
                current = candidate
                continue
            lines.append(current.rstrip())
            current = ""
            if _measure(draw, token, font, stroke)[0] <= max_width:
                current = token
            else:
                chunks = _wrap_long_token(token, draw, font, max_width, stroke)
                lines.extend(chunks[:-1])
                current = chunks[-1] if chunks else ""
        if current.strip():
            lines.append(current.rstrip())
    return lines


def _horizontal_layout(
    text: str,
    size: int,
    box_w: int,
    box_h: int,
    settings: Settings,
    draw,
    style: dict,
):
    font = resolve_font(settings, size, style.get("font_path", ""))
    stroke = int(style["stroke_width"])
    lines = wrap_horizontal(text, draw, font, box_w, stroke)
    if not lines:
        return True, lines, font, 0
    line_h = max(1, max(_measure(draw, line or " ", font, stroke)[1] for line in lines))
    total_h = math.ceil(line_h * len(lines) * float(style["line_spacing"]))
    widest = max((_measure(draw, line, font, stroke)[0] for line in lines), default=0)
    return widest <= box_w and total_h <= box_h, lines, font, line_h


def _draw_horizontal(draw, box, text: str, region: TextRegion, settings: Settings, style: dict) -> dict:
    left, top, right, bottom = box
    margin = settings.box_margin
    box_w = max(1, right - left - margin * 2)
    box_h = max(1, bottom - top - margin * 2)
    chosen = None
    preferred = max(style["min_font_size"], int(style["font_size"]))
    for size in range(preferred, int(style["min_font_size"]) - 1, -1):
        ok, lines, font, line_h = _horizontal_layout(text, size, box_w, box_h, settings, draw, style)
        chosen = (ok, size, lines, font, line_h)
        if ok:
            break
    if chosen is None:
        return {"fits": True, "font_size": preferred, "lines": 0, "box": list(box)}

    ok, size, lines, font, line_h = chosen
    total_h = line_h * len(lines) * float(style["line_spacing"])
    y = top + margin + max(0.0, (box_h - total_h) / 2.0)
    fill = _hex_color(style["text_color"])
    stroke_fill = _hex_color(style["stroke_color"])
    stroke_width = int(style["stroke_width"])
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
        width = bbox[2] - bbox[0]
        x = left + margin + max(0.0, (box_w - width) / 2.0)
        draw.text(
            (x - bbox[0], y - bbox[1]),
            line,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )
        y += line_h * float(style["line_spacing"])
    metrics = {"fits": bool(ok), "font_size": size, "lines": len(lines), "box": list(box)}
    region.metadata["render_metrics"] = metrics
    return metrics


def _vertical_columns(text: str, max_chars: int) -> list[str]:
    chars = [char for char in normalize_layout_text(text) if char != "\n" and not char.isspace()]
    max_chars = max(1, max_chars)
    return ["".join(chars[index:index + max_chars]) for index in range(0, len(chars), max_chars)]


def _vertical_layout(text: str, size: int, box_w: int, box_h: int, settings: Settings, draw, style: dict):
    font = resolve_font(settings, size, style.get("font_path", ""))
    stroke = int(style["stroke_width"])
    _, char_h = _measure(draw, "国", font, stroke)
    char_h = max(char_h, size)
    max_chars = max(1, int(box_h / (char_h * float(style["line_spacing"]))))
    columns = _vertical_columns(text, max_chars)
    col_w = max(size, _measure(draw, "国", font, stroke)[0])
    total_w = col_w * len(columns) * float(style["line_spacing"])
    return total_w <= box_w, columns, font, char_h, col_w


def _draw_vertical(draw, box, text: str, region: TextRegion, settings: Settings, style: dict) -> dict:
    left, top, right, bottom = box
    margin = settings.box_margin
    box_w = max(1, right - left - margin * 2)
    box_h = max(1, bottom - top - margin * 2)
    chosen = None
    preferred = max(style["min_font_size"], int(style["font_size"]))
    for size in range(preferred, int(style["min_font_size"]) - 1, -1):
        ok, columns, font, char_h, col_w = _vertical_layout(text, size, box_w, box_h, settings, draw, style)
        chosen = (ok, size, columns, font, char_h, col_w)
        if ok:
            break
    if chosen is None:
        return {"fits": True, "font_size": preferred, "columns": 0, "box": list(box)}

    ok, size, columns, font, char_h, col_w = chosen
    spacing = float(style["line_spacing"])
    total_w = col_w * len(columns) * spacing
    x = right - margin - col_w - max(0.0, (box_w - total_w) / 2.0)
    punctuation = set("。、，！？：；…（）()「」『』【】《》〈〉")
    fill = _hex_color(style["text_color"])
    stroke_fill = _hex_color(style["stroke_color"])
    stroke_width = int(style["stroke_width"])
    for column in columns:
        col_height = char_h * len(column) * spacing
        y = top + margin + max(0.0, (box_h - col_height) / 2.0)
        for char in column:
            bbox = draw.textbbox((0, 0), char, font=font, stroke_width=stroke_width)
            char_w = bbox[2] - bbox[0]
            dx = max(0.0, (col_w - char_w) / 2.0)
            dy = -size * 0.08 if char in punctuation else 0.0
            draw.text(
                (x + dx - bbox[0], y + dy - bbox[1]),
                char,
                font=font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
            )
            y += char_h * spacing
        x -= col_w * spacing
    metrics = {"fits": bool(ok), "font_size": size, "columns": len(columns), "box": list(box)}
    region.metadata["render_metrics"] = metrics
    return metrics


def _region_layout_box(region: TextRegion) -> tuple[int, int, int, int]:
    stored = region.metadata.get("typeset_box")
    if isinstance(stored, list) and len(stored) == 4:
        return tuple(map(int, stored))
    return region.box


def assess_region_typesetting(region: TextRegion, text: str, settings: Settings) -> dict:
    text = text.strip()
    style = resolve_region_style(region, settings)
    if not text:
        return {"fits": True, "font_size": style["font_size"], "overflow": False, "columns": 0}
    left, top, right, bottom = _region_layout_box(region)
    width = max(2, right - left)
    height = max(2, bottom - top)
    scratch = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(scratch)
    margin = settings.box_margin
    box_w = max(1, width - margin * 2)
    box_h = max(1, height - margin * 2)
    direction = settings.typeset_direction
    if direction == "auto":
        direction = region.direction if region.direction in {"horizontal", "vertical"} else (
            "vertical" if region.h > region.w * 1.2 else "horizontal"
        )

    preferred = max(style["min_font_size"], int(style["font_size"]))
    if direction == "horizontal":
        last = None
        for size in range(preferred, int(style["min_font_size"]) - 1, -1):
            ok, lines, _font, _line_h = _horizontal_layout(text, size, box_w, box_h, settings, draw, style)
            last = (ok, size, len(lines))
            if ok:
                return {"fits": True, "font_size": size, "overflow": False, "columns": len(lines)}
        size = last[1] if last else style["min_font_size"]
        return {"fits": False, "font_size": size, "overflow": True, "columns": last[2] if last else 0}

    last = None
    for size in range(preferred, int(style["min_font_size"]) - 1, -1):
        ok, columns, _font, _char_h, _col_w = _vertical_layout(text, size, box_w, box_h, settings, draw, style)
        last = (ok, size, len(columns))
        if ok:
            return {"fits": True, "font_size": size, "overflow": False, "columns": len(columns)}
    size = last[1] if last else style["min_font_size"]
    return {"fits": False, "font_size": size, "overflow": True, "columns": last[2] if last else 0}


def typeset_translations(image: Image.Image, regions: list[TextRegion], settings: Settings) -> Image.Image:
    output = image.convert("RGB")
    draw = ImageDraw.Draw(output)
    for region in regions:
        if not region.enabled:
            continue
        if settings.preserve_sfx and region.region_type == "sfx" and not settings.translate_sfx:
            continue
        text = region.translation.strip() or region.source.strip()
        if not text:
            continue
        box = resolve_typeset_box(output, region, settings)
        style = resolve_region_style(region, settings)
        region.metadata["resolved_render_style"] = dict(style)
        direction = settings.typeset_direction
        if direction == "auto":
            source_direction = (region.metadata.get("source_style") or {}).get("direction")
            direction = region.direction if region.direction in {"horizontal", "vertical"} else (
                source_direction if source_direction in {"horizontal", "vertical"} else (
                    "vertical" if region.h > region.w * 1.2 else "horizontal"
                )
            )
        if direction == "vertical":
            _draw_vertical(draw, box, text, region, settings, style)
        else:
            _draw_horizontal(draw, box, text, region, settings, style)
    return output


def save_image(image: Image.Image, output_path: Path, settings: Settings) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() in {".jpg", ".jpeg"}:
        image.save(output_path, quality=settings.jpeg_quality, subsampling=0)
    else:
        image.save(output_path)
