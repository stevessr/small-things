from __future__ import annotations

import hashlib
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .models import Settings


@dataclass(frozen=True)
class ModelSpec:
    key: str
    relative_path: str
    url: str
    sha256: str
    size: int | None = None


# Only models with independently published SHA-256 digests are eligible for automatic download.
# The CTD digest is published by the Hugging Face Xet pointer for the upstream ONNX file.
# The LaMa digest is published by multiple mirrors for the same upstream TorchScript model.
MODEL_SPECS: dict[str, ModelSpec] = {
    "ctd": ModelSpec(
        key="ctd",
        relative_path="models/ctd/comictextdetector.pt.onnx",
        url="https://huggingface.co/spaces/III111II1I1/detector/resolve/main/data/comictextdetector.pt.onnx?download=true",
        sha256="1a86ace74961413cbd650002e7bb4dcec4980ffa21b2f19b86933372071d718f",
        size=94_669_756,
    ),
    "lama": ModelSpec(
        key="lama",
        relative_path="models/lama/big-lama.pt",
        url="https://huggingface.co/signature-ai/big-lama/resolve/main/big-lama.pt?download=true",
        sha256="344c77bbcb158f17dd143070d1e789f38a66c04202311ae3a258ef66667a9ea9",
        size=205_669_692,
    ),
}


def cache_root(settings: Settings | None = None) -> Path:
    if settings and settings.model_cache_dir:
        return Path(settings.model_cache_dir).expanduser()
    override = os.getenv("SMALL_THINGS_AUTO_MANGA_CACHE", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "small-things" / "auto-manga"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify_model(path: Path, spec: ModelSpec) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    if spec.size is not None and path.stat().st_size != spec.size:
        raise RuntimeError(
            f"Model size mismatch for {spec.key}: expected {spec.size}, got {path.stat().st_size}; refusing to load {path}"
        )
    actual = sha256_file(path)
    if actual.lower() != spec.sha256.lower():
        raise RuntimeError(
            f"SHA256 mismatch for {spec.key}: expected {spec.sha256}, got {actual}; refusing to load {path}"
        )


def ensure_model(
    key: str,
    settings: Settings | None = None,
    *,
    allow_download: bool = True,
    progress=None,
) -> Path:
    if key not in MODEL_SPECS:
        raise KeyError(f"No verified model spec registered for {key}")
    spec = MODEL_SPECS[key]
    destination = cache_root(settings) / spec.relative_path
    if destination.exists():
        verify_model(destination, spec)
        return destination
    if not allow_download:
        raise FileNotFoundError(destination)

    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    try:
        request = urllib.request.Request(spec.url, headers={"User-Agent": "small-things-auto-manga/1"})
        with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as handle:
            total = int(response.headers.get("Content-Length") or spec.size or 0)
            downloaded = 0
            digest = hashlib.sha256()
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                if progress and total:
                    progress(downloaded / total, f"Downloading {key}: {downloaded}/{total}")
        actual = digest.hexdigest()
        if actual.lower() != spec.sha256.lower():
            raise RuntimeError(
                f"SHA256 mismatch for downloaded {key}: expected {spec.sha256}, got {actual}; refusing model"
            )
        if spec.size is not None and part.stat().st_size != spec.size:
            raise RuntimeError(
                f"Downloaded {key} has unexpected size {part.stat().st_size}, expected {spec.size}; refusing model"
            )
        part.replace(destination)
        return destination
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, RuntimeError):
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        raise
