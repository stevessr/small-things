from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

from .models import Settings, TextRegion


_MANGA_OCR_MODEL = None


def normalize_text(text: str) -> str:
    text = text.replace("\u3000", " ").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _post_chat(base_url: str, api_key: str, payload: dict, retries: int = 2) -> dict:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last_error = exc
            if attempt >= retries:
                raise RuntimeError(f"API request failed: {exc}") from exc
            time.sleep(min(8.0, 1.5 * (2**attempt)))
    raise RuntimeError(str(last_error))


def _extract_chat_text(data: dict) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected chat completion response: {data}") from exc
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                parts.append(str(item.get("text", "")))
        return "\n".join(parts).strip()
    return str(content).strip()


def _ocr_manga(crop: Image.Image) -> str:
    global _MANGA_OCR_MODEL
    try:
        from manga_ocr import MangaOcr
    except ImportError as exc:
        raise RuntimeError("manga-ocr is not installed. Run: pip install manga-ocr") from exc
    if _MANGA_OCR_MODEL is None:
        _MANGA_OCR_MODEL = MangaOcr()
    return str(_MANGA_OCR_MODEL(crop)).strip()


def _ocr_openai_vision(crop: Image.Image, settings: Settings) -> str:
    buffer = io.BytesIO()
    crop.convert("RGB").save(buffer, format="JPEG", quality=92)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    prompt = (
        "Transcribe all manga/comic text in this crop exactly. Preserve reading order. "
        "Return only the text, no explanation. "
        f"Expected source language: {settings.ocr_language}."
    )
    payload = {
        "model": settings.vision_model,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                    },
                ],
            }
        ],
    }
    return _extract_chat_text(
        _post_chat(settings.vision_base_url, settings.vision_api_key, payload, retries=2)
    )


def _preserved_sfx(region: TextRegion, settings: Settings) -> bool:
    return settings.preserve_sfx and region.region_type == "sfx" and not settings.translate_sfx


def ocr_regions(image: Image.Image, regions: list[TextRegion], settings: Settings, progress=None) -> None:
    if settings.ocr_backend == "none":
        return
    active = [region for region in regions if region.enabled and not _preserved_sfx(region, settings)]
    total = max(1, len(active))
    for index, region in enumerate(active):
        crop = image.crop(region.box)
        try:
            if settings.ocr_backend == "manga_ocr":
                text = _ocr_manga(crop)
            elif settings.ocr_backend == "openai_vision":
                text = _ocr_openai_vision(crop, settings)
            else:
                raise ValueError(f"Unsupported OCR backend: {settings.ocr_backend}")
            region.source = normalize_text(text)
            region.metadata.pop("ocr_error", None)
            region.metadata["ocr_backend"] = settings.ocr_backend
            message = region.source[:80]
        except Exception as exc:
            # A single OCR crop must not terminate a whole chapter/volume.
            region.source = ""
            region.metadata["ocr_error"] = f"{type(exc).__name__}: {exc}"
            message = f"OCR failed: {type(exc).__name__}"
        if progress:
            progress("ocr", (index + 1) / total, message)


def load_glossary(path: str) -> dict[str, str]:
    if not path:
        return {}
    source = Path(path).expanduser()
    if not source.exists():
        raise FileNotFoundError(source)
    if source.suffix.lower() == ".json":
        data = json.loads(source.read_text("utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Glossary JSON must be an object: {source}")
        return {str(key): str(value) for key, value in data.items()}
    result: dict[str, str] = {}
    for line in source.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            left, right = line.split("\t", 1)
        elif "=" in line:
            left, right = line.split("=", 1)
        else:
            continue
        result[left.strip()] = right.strip()
    return result


def glossary_fingerprint(glossary: dict[str, str]) -> str:
    raw = json.dumps(glossary, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def translation_context_fingerprint(settings: Settings, glossary: dict[str, str] | None = None) -> str:
    glossary = load_glossary(settings.glossary_path) if glossary is None else glossary
    payload = {
        "target": settings.target_language,
        "provider": settings.translation_provider,
        "base_url": settings.translation_base_url.rstrip("/"),
        "model": settings.translation_model,
        "glossary": glossary_fingerprint(glossary),
        "translate_sfx": settings.translate_sfx,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _tm_path(output_root: Path) -> Path:
    return output_root / ".auto-manga-tm.json"


def load_translation_memory(output_root: Path) -> dict[str, str]:
    path = _tm_path(output_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_translation_memory(output_root: Path, memory: dict[str, str]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    path = _tm_path(output_root)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(memory, ensure_ascii=False, indent=2), "utf-8")
    temp.replace(path)


def translation_memory_key(
    source: str,
    target: str,
    provider: str = "",
    model: str = "",
    glossary_hash: str = "",
) -> str:
    payload = {
        "source": normalize_text(source),
        "target": target,
        "provider": provider,
        "model": model,
        "glossary": glossary_hash,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _translate_batch(texts: list[str], settings: Settings, glossary: dict[str, str]) -> list[str]:
    glossary_text = "\n".join(f"{key} => {value}" for key, value in glossary.items())
    instruction = (
        "You are translating manga/comic dialogue and narration. "
        f"Translate into {settings.target_language}. "
        "Keep each item concise and natural for typesetting. Preserve names, tone, "
        "honorific intent and punctuation appropriately. "
        "Return ONLY a JSON array of translated strings in exactly the same order "
        "and length as the input array."
    )
    if settings.translate_sfx:
        instruction += " Translate sound effects naturally when an input item is an SFX region."
    if glossary_text:
        instruction += "\nMandatory glossary:\n" + glossary_text
    payload = {
        "model": settings.translation_model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": json.dumps(texts, ensure_ascii=False)},
        ],
    }
    raw = _extract_chat_text(
        _post_chat(
            settings.translation_base_url,
            settings.translation_api_key,
            payload,
            retries=settings.translation_retries,
        )
    ).strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Translator returned invalid JSON: {raw[:500]}") from exc
    if not isinstance(data, list) or len(data) != len(texts):
        count = len(data) if isinstance(data, list) else "non-list"
        raise RuntimeError(f"Translator returned {count} items for {len(texts)} inputs")
    return [normalize_text(str(item)) for item in data]


def translate_regions(regions: list[TextRegion], settings: Settings, output_root: Path, progress=None) -> None:
    active = [
        region
        for region in regions
        if region.enabled and region.source.strip() and not _preserved_sfx(region, settings)
    ]
    if not active:
        return
    if settings.translation_provider == "none":
        for region in active:
            region.translation = region.source
            region.metadata.pop("translation_error", None)
            region.metadata["translation_backend"] = "none"
        return
    if settings.translation_provider != "openai_compatible":
        raise ValueError(f"Unsupported translation provider: {settings.translation_provider}")

    glossary = load_glossary(settings.glossary_path)
    glossary_hash = glossary_fingerprint(glossary)
    memory = load_translation_memory(output_root) if settings.use_translation_memory else {}
    pending: list[TextRegion] = []
    for region in active:
        key = translation_memory_key(
            region.source,
            settings.target_language,
            settings.translation_provider,
            settings.translation_model,
            glossary_hash,
        )
        if key in memory:
            region.translation = memory[key]
            region.metadata["translation_memory_hit"] = True
            region.metadata.pop("translation_error", None)
        else:
            region.metadata["translation_memory_hit"] = False
            pending.append(region)

    batch_size = max(1, settings.translation_batch_size)
    done = len(active) - len(pending)
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        try:
            translations = _translate_batch([region.source for region in batch], settings, glossary)
        except Exception as exc:
            # API failures are quality/review data, not a reason to terminate the volume.
            error = f"{type(exc).__name__}: {exc}"
            for region in batch:
                region.translation = ""
                region.metadata["translation_error"] = error
            done += len(batch)
            if progress:
                progress("translate", done / len(active), f"translation failed for {len(batch)} region(s)")
            continue

        for region, translated in zip(batch, translations):
            region.translation = translated
            region.metadata.pop("translation_error", None)
            region.metadata["translation_backend"] = settings.translation_provider
            if settings.use_translation_memory:
                key = translation_memory_key(
                    region.source,
                    settings.target_language,
                    settings.translation_provider,
                    settings.translation_model,
                    glossary_hash,
                )
                memory[key] = translated
        done += len(batch)
        if progress:
            progress("translate", done / len(active), f"{done}/{len(active)}")

    if settings.use_translation_memory:
        save_translation_memory(output_root, memory)
