import os
import platform
import shutil
import psutil


def get_system_info() -> dict:
    """Return basic information about the local computer."""

    return {
        "computer_name": platform.node(),
        "operating_system": platform.system(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
    }


def get_cpu_usage() -> dict:
    """Return CPU usage information."""

    return {
        "cpu_percent": psutil.cpu_percent(interval=1),
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
    }


def get_memory_usage() -> dict:
    """Return system memory usage."""

    memory = psutil.virtual_memory()

    return {
        "total_gb": round(memory.total / (1024 ** 3), 2),
        "available_gb": round(memory.available / (1024 ** 3), 2),
        "used_gb": round(memory.used / (1024 ** 3), 2),
        "percent_used": memory.percent,
    }


def get_disk_usage() -> dict:
    """Return disk usage for the current drive."""

    drive = os.path.abspath(os.sep)

    usage = shutil.disk_usage(drive)

    return {
        "drive": drive,
        "total_gb": round(usage.total / (1024 ** 3), 2),
        "used_gb": round(usage.used / (1024 ** 3), 2),
        "free_gb": round(usage.free / (1024 ** 3), 2),
    }


def get_running_processes(limit: int = 15) -> list:
    """Return some currently running processes."""

    processes = []

    for process in psutil.process_iter(
        ["pid", "name", "cpu_percent", "memory_percent"]
    ):
        try:
            processes.append(process.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    processes = sorted(
        processes,
        key=lambda x: x.get("memory_percent") or 0,
        reverse=True,
    )

    return processes[:limit]