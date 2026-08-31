#!/usr/bin/env python3

import os
import platform
import shutil
import subprocess
from pathlib import Path


def line():
    print("-" * 60)


def section(title):
    print()
    print(f"## {title}")
    line()


def status(label, message, ok=None):
    if ok is True:
        prefix = "OK  "
    elif ok is False:
        prefix = "FAIL"
    else:
        prefix = "INFO"

    print(f"{prefix} {label}: {message}")


def read_first_match(path, prefix):
    file_path = Path(path)

    if not file_path.exists():
        return None

    try:
        for line_text in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line_text.startswith(prefix):
                return line_text.split(":", 1)[1].strip()
    except Exception:
        return None

    return None


def read_meminfo():
    values = {}

    path = Path("/proc/meminfo")

    if not path.exists():
        return values

    try:
        for line_text in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if ":" not in line_text:
                continue

            key, value = line_text.split(":", 1)
            parts = value.strip().split()

            if not parts:
                continue

            try:
                values[key] = int(parts[0])
            except ValueError:
                continue

    except Exception:
        return {}

    return values


def format_kib(value):
    if value is None:
        return "unknown"

    gib = value / 1024 / 1024
    return f"{gib:.2f} GiB"


def show_basic_system():
    section("System")

    status("Hostname", platform.node() or "unknown", ok=True)
    status("OS", platform.platform(), ok=True)
    status("Kernel", platform.release(), ok=True)
    status("Python", platform.python_version(), ok=True)

    uptime_path = Path("/proc/uptime")

    if uptime_path.exists():
        try:
            seconds = float(uptime_path.read_text().split()[0])
            hours = seconds / 3600
            status("Uptime", f"{hours:.2f} hours", ok=True)
        except Exception:
            status("Uptime", "unknown", ok=None)


def show_cpu():
    section("CPU")

    model = read_first_match("/proc/cpuinfo", "model name")
    status("Model", model or platform.processor() or "unknown", ok=True)
    status("Logical Cores", str(os.cpu_count() or "unknown"), ok=True)

    load = os.getloadavg() if hasattr(os, "getloadavg") else None

    if load:
        status("Load Average", f"{load[0]:.2f}, {load[1]:.2f}, {load[2]:.2f}", ok=True)


def show_memory():
    section("Memory")

    meminfo = read_meminfo()

    total = meminfo.get("MemTotal")
    available = meminfo.get("MemAvailable")
    swap_total = meminfo.get("SwapTotal")
    swap_free = meminfo.get("SwapFree")

    status("RAM Total", format_kib(total), ok=True)
    status("RAM Available", format_kib(available), ok=True)

    if swap_total is not None:
        used = None

        if swap_free is not None:
            used = swap_total - swap_free

        status("Swap Total", format_kib(swap_total), ok=True)
        status("Swap Used", format_kib(used), ok=True)


def show_disk():
    section("Disk")

    try:
        usage = shutil.disk_usage("/")
        status("Root Total", f"{usage.total / 1024**3:.2f} GiB", ok=True)
        status("Root Used", f"{usage.used / 1024**3:.2f} GiB", ok=True)
        status("Root Free", f"{usage.free / 1024**3:.2f} GiB", ok=True)
    except Exception as e:
        status("Root Disk", str(e), ok=False)


def show_gpu():
    section("GPU")

    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used,temperature.gpu,power.draw,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]

    try:
        result = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=5,
        )
    except FileNotFoundError:
        status("NVIDIA", "nvidia-smi not found", ok=None)
        return
    except Exception as e:
        status("NVIDIA", str(e), ok=False)
        return

    if result.returncode != 0:
        status("NVIDIA", result.stdout.strip() or f"exit code {result.returncode}", ok=False)
        return

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]

    if not lines:
        status("NVIDIA", "no GPU rows returned", ok=None)
        return

    for index, row in enumerate(lines, start=1):
        parts = [part.strip() for part in row.split(",")]

        while len(parts) < 6:
            parts.append("unknown")

        name, mem_total, mem_used, temp, power, util = parts[:6]

        status(f"GPU {index}", name, ok=True)
        status(f"GPU {index} VRAM", f"{mem_used} / {mem_total} MiB", ok=True)
        status(f"GPU {index} Temp", f"{temp} C", ok=True)
        status(f"GPU {index} Power", f"{power} W", ok=True)
        status(f"GPU {index} Util", f"{util} %", ok=True)


def main():
    print("MEMORIA SYSTEM / HARDWARE SNAPSHOT")
    line()
    print("Read-only local system snapshot. No config changes. No private content.")
    line()

    show_basic_system()
    show_cpu()
    show_memory()
    show_disk()
    show_gpu()

    section("Result")
    status("System Snapshot", "completed", ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
