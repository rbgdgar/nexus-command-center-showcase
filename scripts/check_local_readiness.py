"""Read-only local readiness inventory for NEXUS and Qwen3.8."""

from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.request
from pathlib import Path

import psutil


def ollama_binary() -> str | None:
    installed = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe"
    return shutil.which("ollama") or (str(installed) if installed.is_file() else None)


def ollama_models() -> tuple[bool, list[str]]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as response:
            payload = json.loads(response.read())
        return True, sorted(item["name"] for item in payload.get("models", []))
    except (OSError, ValueError, urllib.error.URLError):
        return False, []


def inventory() -> dict:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(Path.cwd().anchor or "/")
    online, models = ollama_models()
    enough_capacity = memory.total >= 24 * 2**30 and disk.free >= 24 * 2**30
    return {
        "python": os.sys.version.split()[0],
        "ram_gb": round(memory.total / 2**30, 1),
        "available_ram_gb": round(memory.available / 2**30, 1),
        "free_disk_gb": round(disk.free / 2**30, 1),
        "ollama": {"installed": bool(ollama_binary()), "online": online, "models": models},
        "recommended_model": (
            "qwen3.8:27b" if enough_capacity
            else "Use a hosted model; Qwen3.8 27B needs substantial memory"
        ),
        "qwen3_8_27b_capacity": enough_capacity,
    }


if __name__ == "__main__":
    print(json.dumps(inventory(), indent=2))
