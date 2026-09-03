from __future__ import annotations

import math
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from .models import Settings, TextRegion
from .masking import build_text_mask
from .inpainters import InpaintRun, inpaint_with_backend


def _hex_color(value: str) -> tuple[int, int, int]:
    value=value.strip().lstrip('#')
    if len(value)==3: value=''.join(c*2 for c in value)
    if len(value)!=6: raise ValueError(f'Invalid color: {value}')
    return tuple(int(value[i:i+2],16) for i in (0,2,4))


def erase_original_text_with_report(image: Image.Image, regions: list[TextRegion], settings: Settings) -> InpaintRun:
    mask = build_text_mask(image, regions, settings)
    if not np.any(mask):
        return InpaintRun(image.convert("RGB"), "none", [])
    run = inpaint_with_backend(image, mask, settings)
    for region in regions:
        if not region.enabled or (settings.preserve_sfx and region.region_type == "sfx" and not settings.translate_sfx):
            continue
        region.metadata["inpainter"] = run.backend
        if run.fallback_reasons:
            region.metadata["inpaint_fallbacks"] = list(run.fallback_reasons)
    return run


def erase_original_text(image: Image.Image, regions: list[TextRegion], settings: Settings) -> Image.Image:
    return erase_original_text_with_report(image, regions, settings).image


def resolve_font(settings: Settings, size: int):
    if settings.font_path: return ImageFont.truetype(settings.font_path,size=size)
    candidates=['/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc','/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf','/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc','/System/Library/Fonts/PingFang.ttc','C:/Windows/Fonts/msyh.ttc','C:/Windows/Fonts/simhei.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    for candidate in candidates:
        if Path(candidate).exists():
            try: return ImageFont.truetype(candidate,size=size)
            except OSError: pass
    return ImageFont.load_default()


def _measure(draw,text,font,stroke=0):
    if not text:return (0,0)
    box=draw.textbbox((0,0),text,font=font,stroke_width=stroke); return box[2]-box[0],box[3]-box[1]


def normalize_layout_text(text:str)->str:
    return ' '.join(text.replace('\u3000',' ').split()) if '\n' not in text else '\n'.join(' '.join(line.split()) for line in text.splitlines()).strip()


def wrap_horizontal(text,draw,font,max_width,stroke=0):
    text=normalize_layout_text(text)
    if not text:return []
    lines=[]
    for paragraph in text.splitlines() or [text]:
        if not paragraph: lines.append(''); continue
        current=''
        for char in paragraph:
            candidate=current+char
            if current and _measure(draw,candidate,font,stroke)[0]>max_width: lines.append(current); current=char
            else: current=candidate
        if current: lines.append(current)
    return lines


def _horizontal_layout(text,size,box_w,box_h,settings,draw):
    font=resolve_font(settings,size); lines=wrap_horizontal(text,draw,font,box_w,settings.stroke_width)
    if not lines:return True,lines,font,0
    line_h=max(1,max(_measure(draw,line or ' ',font,settings.stroke_width)[1] for line in lines)); total_h=math.ceil(line_h*len(lines)*settings.line_spacing); widest=max((_measure(draw,line,font,settings.stroke_width)[0] for line in lines),default=0)
    return widest<=box_w and total_h<=box_h,lines,font,line_h


def _draw_horizontal(draw,region,text,settings,fill,stroke_fill):
    margin=settings.box_margin; box_w=max(1,region.w-margin*2); box_h=max(1,region.h-margin*2); chosen=None
    for size in range(settings.font_size,settings.min_font_size-1,-2):
        ok,lines,font,line_h=_horizontal_layout(text,size,box_w,box_h,settings,draw); chosen=(lines,font,line_h)
        if ok: break
    lines,font,line_h=chosen or ([],resolve_font(settings,settings.min_font_size),settings.min_font_size)
    total_h=line_h*len(lines)*settings.line_spacing; y=region.y+margin+max(0,(box_h-total_h)/2)
    for line in lines:
        width,_=_measure(draw,line,font,settings.stroke_width); x=region.x+margin+max(0,(box_w-width)/2)
        draw.text((x,y),line,font=font,fill=fill,stroke_width=settings.stroke_width,stroke_fill=stroke_fill); y += line_h*settings.line_spacing


def _vertical_columns(text,max_chars):
    chars=[c for c in normalize_layout_text(text) if c!='\n']; max_chars=max(1,max_chars); return [''.join(chars[i:i+max_chars]) for i in range(0,len(chars),max_chars)]


def _draw_vertical(draw,region,text,settings,fill,stroke_fill):
    margin=settings.box_margin; box_w=max(1,region.w-margin*2); box_h=max(1,region.h-margin*2); chosen=None
    for size in range(settings.font_size,settings.min_font_size-1,-2):
        font=resolve_font(settings,size); _,char_h=_measure(draw,'国',font,settings.stroke_width); char_h=max(char_h,size); max_chars=max(1,int(box_h/(char_h*settings.line_spacing))); columns=_vertical_columns(text,max_chars); col_w=max(size,_measure(draw,'国',font,settings.stroke_width)[0]); total_w=col_w*len(columns)*settings.line_spacing; chosen=(size,font,char_h,col_w,columns)
        if total_w<=box_w: break
    if not chosen:return
    size,font,char_h,col_w,columns=chosen; total_w=col_w*len(columns)*settings.line_spacing; x=region.x+region.w-margin-col_w-max(0,(box_w-total_w)/2); punctuation=set('。、，！？：；…（）()「」『』【】')
    for column in columns:
        col_height=char_h*len(column)*settings.line_spacing; y=region.y+margin+max(0,(box_h-col_height)/2)
        for char in column:
            char_w,_=_measure(draw,char,font,settings.stroke_width); dx=max(0,(col_w-char_w)/2); dy=-size*0.08 if char in punctuation else 0
            draw.text((x+dx,y+dy),char,font=font,fill=fill,stroke_width=settings.stroke_width,stroke_fill=stroke_fill); y += char_h*settings.line_spacing
        x -= col_w*settings.line_spacing


def assess_region_typesetting(region: TextRegion, text: str, settings: Settings) -> dict:
    text = text.strip()
    if not text:
        return {"fits": True, "font_size": settings.font_size, "overflow": False, "columns": 0}
    scratch = Image.new("RGB", (max(2, region.w), max(2, region.h)), "white")
    draw = ImageDraw.Draw(scratch)
    margin = settings.box_margin
    box_w = max(1, region.w - margin * 2)
    box_h = max(1, region.h - margin * 2)
    direction = settings.typeset_direction
    if direction == "auto":
        direction = region.direction if region.direction in {"horizontal", "vertical"} else ("vertical" if region.h > region.w * 1.2 else "horizontal")
    if direction == "horizontal":
        last = None
        for size in range(settings.font_size, settings.min_font_size - 1, -2):
            ok, lines, _font, _line_h = _horizontal_layout(text, size, box_w, box_h, settings, draw)
            last = (ok, size, len(lines))
            if ok:
                return {"fits": True, "font_size": size, "overflow": False, "columns": len(lines)}
        size = last[1] if last else settings.min_font_size
        return {"fits": False, "font_size": size, "overflow": True, "columns": last[2] if last else 0}
    last = None
    for size in range(settings.font_size, settings.min_font_size - 1, -2):
        font = resolve_font(settings, size)
        _, char_h = _measure(draw, "国", font, settings.stroke_width)
        char_h = max(char_h, size)
        max_chars = max(1, int(box_h / (char_h * settings.line_spacing)))
        columns = _vertical_columns(text, max_chars)
        col_w = max(size, _measure(draw, "国", font, settings.stroke_width)[0])
        total_w = col_w * len(columns) * settings.line_spacing
        ok = total_w <= box_w
        last = (ok, size, len(columns))
        if ok:
            return {"fits": True, "font_size": size, "overflow": False, "columns": len(columns)}
    size = last[1] if last else settings.min_font_size
    return {"fits": False, "font_size": size, "overflow": True, "columns": last[2] if last else 0}


def typeset_translations(image,regions,settings):
    output=image.convert('RGB'); draw=ImageDraw.Draw(output); fill=_hex_color(settings.text_color); stroke_fill=_hex_color(settings.stroke_color)
    for region in regions:
        if not region.enabled: continue
        if settings.preserve_sfx and region.region_type == 'sfx' and not settings.translate_sfx: continue
        text=region.translation.strip() or region.source.strip()
        if not text: continue
        direction=settings.typeset_direction
        if direction=='auto': direction=region.direction if region.direction in {'horizontal','vertical'} else ('vertical' if region.h>region.w*1.2 else 'horizontal')
        if direction=='vertical': _draw_vertical(draw,region,text,settings,fill,stroke_fill)
        else: _draw_horizontal(draw,region,text,settings,fill,stroke_fill)
    return output


def save_image(image,output_path,settings):
    output_path.parent.mkdir(parents=True,exist_ok=True)
    if output_path.suffix.lower() in {'.jpg','.jpeg'}: image.save(output_path,quality=settings.jpeg_quality,subsampling=0)
    else: image.save(output_path)
