"""Read-only host diagnostics for AgentOS: never start agents or Docker."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from importlib.resources import files
from pathlib import Path


def inspect_environment(backend: str = "host", ui: str = "web") -> list[dict[str, str]]:
    """Report prerequisites without modifying state or running Docker commands."""
    if backend not in {"host", "layerfs"} or ui not in {"web", "gpui"}:
        raise ValueError("backend must be host/layerfs and ui must be web/gpui")
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    linux = platform.system() == "Linux"
    add("operating_system", "ok" if linux else "fail",
        f"{platform.system()} {platform.release()}; Linux required for supervisor")
    supported = sys.version_info >= (3, 11)
    add("python", "ok" if supported else "fail",
        f"Python {sys.version_info.major}.{sys.version_info.minor} (requires >=3.11)")
    try:
        packaged = files("agentos").joinpath("ui", "index.html").is_file()
    except (ModuleNotFoundError, OSError):
        packaged = False
    add("dashboard_assets", "ok" if packaged else "fail",
        "HTML/JS assets installed" if packaged else "missing agentos/ui/index.html")

    if backend == "host":
        cgroup = Path("/sys/fs/cgroup/cgroup.controllers")
        add("cgroup_v2", "ok" if cgroup.exists() else "warn",
            "cgroup v2 detected; delegation/permissions are NOT verified"
            if cgroup.exists() else "No unified cgroup v2 mount; RLIMIT fallback only")
    else:
        node = shutil.which("node")
        if not node:
            add("node", "fail", "Node >=20 required for @layerfs/agent")
        else:
            try:
                version = subprocess.run([node, "--version"], capture_output=True,
                                         text=True, timeout=3, check=True).stdout.strip()
                major = int(version.lstrip("v").split(".", 1)[0])
                add("node", "ok" if major >= 20 else "fail", version)
            except (OSError, ValueError, subprocess.CalledProcessError,
                    subprocess.TimeoutExpired):
                add("node", "fail", "Could not verify Node version")
        add("docker", "ok" if shutil.which("docker") else "fail",
            "Docker CLI found; daemon access NOT verified" if shutil.which("docker")
            else "Docker CLI missing; LayerFS sandbox needs Docker")
        project = os.getenv("LAYERFS_PROJECT", "")
        add("layerfs_project", "ok" if project else "fail",
            f"selected project: {project}" if project else "set LAYERFS_PROJECT")
        module = os.getenv("LAYERFS_AGENT_MODULE")
        add("layerfs_sdk", "ok" if module and Path(module).is_file() else "warn",
            "explicit SDK module file found" if module and Path(module).is_file()
            else "SDK module must resolve as @layerfs/agent or LAYERFS_AGENT_MODULE")
        add("layerfs_runtime", "warn",
            "SDK native binding / daemon / Store / FUSE / Docker permissions require real integration test")

    if ui == "gpui":
        display = "WAYLAND_DISPLAY" if os.environ.get("WAYLAND_DISPLAY") else (
            "DISPLAY" if os.environ.get("DISPLAY") else "")
        add("graphical_session", "ok" if display else "warn",
            f"{display} present; Vulkan/graphics pipeline not validated"
            if display else "No Wayland/X11 display; native GPUI requires graphical session")
        add("cargo", "ok" if shutil.which("cargo") else "fail",
            "Cargo installed; native GPU compilation NOT verified"
            if shutil.which("cargo") else "Install Rust toolchain for GPUI frontend")
    elif linux:
        add("inotify", "ok" if Path("/proc/sys/fs/inotify/max_user_watches").exists()
            else "warn",
            "Kernel inotify exposed; per-directory watch availability not verified")
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only AgentOS deployment diagnostics")
    parser.add_argument("--backend", choices=["host", "layerfs"], default="host")
    parser.add_argument("--ui", choices=["web", "gpui"], default="web")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()
    checks = inspect_environment(args.backend, args.ui)
    if args.format == "json":
        print(json.dumps({"backend": args.backend, "ui": args.ui, "checks": checks},
                         ensure_ascii=False, indent=2))
    else:
        for c in checks:
            print(f"{c['status'].upper():4s} {c['name']}: {c['detail']}")
    return 2 if any(c["status"] == "fail" for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
