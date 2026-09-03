from __future__ import annotations


def resolve_runtime_profile(profile: str) -> str:
    profile = (profile or "auto").lower()
    if profile != "auto":
        if profile not in {"cpu", "low_vram", "balanced", "quality"}:
            raise ValueError(f"Unsupported runtime profile: {profile}")
        return profile
    try:
        import torch
        if not torch.cuda.is_available():
            return "cpu"
        props = torch.cuda.get_device_properties(torch.cuda.current_device())
        vram_gb = props.total_memory / (1024 ** 3)
        if vram_gb < 6:
            return "low_vram"
        if vram_gb < 10:
            return "balanced"
        return "quality"
    except Exception:
        return "cpu"


def inference_size(profile: str) -> int:
    resolved = resolve_runtime_profile(profile)
    return {"cpu": 1024, "low_vram": 1024, "balanced": 1536, "quality": 2048}[resolved]
