#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if "MEMORIA_ROOT" in os.environ:
    ROOT = Path(os.environ["MEMORIA_ROOT"]).resolve()
else:
    import sys as _memoria_storage_manager_sys

    _MEMORIA_TOOLS_DIR = Path(__file__).resolve().parent
    if str(_MEMORIA_TOOLS_DIR) not in _memoria_storage_manager_sys.path:
        _memoria_storage_manager_sys.path.insert(0, str(_MEMORIA_TOOLS_DIR))

    try:
        from memoria_memory_storage_manager import active_storage_root as _memoria_active_storage_root

        ROOT = _memoria_active_storage_root()
    except Exception:
        ROOT = PROJECT_ROOT.resolve()
CONFIG_PATH = Path(
    os.environ.get(
        "MEMORIA_STORAGE_WATCHDOG_CONFIG",
        str(ROOT / "config" / "memory_storage_watchdog.json"),
    )
)

DEFAULT_CONFIG = {
    "enabled": True,
    "schema_version": "memory-storage-watchdog-v0.1",
    "warning_thresholds_gib": [10, 50, 100],
    "custom_warning_threshold_gib": None,
    "hard_stop_min_free_bytes": 524288000,
    "watched_paths": [
        "knowledge/memory",
        "knowledge/memory_candidates",
        "conversations",
        "summaries",
        "logs",
        "imports",
        "attachments",
    ],
    "filesystem_path": ".",
}


def bytes_to_gib(value: int) -> float:
    return value / 1024 / 1024 / 1024


def format_bytes(value: int) -> str:
    if value >= 1024**3:
        return f"{bytes_to_gib(value):.2f} GiB"
    if value >= 1024**2:
        return f"{value / 1024 / 1024:.2f} MiB"
    if value >= 1024:
        return f"{value / 1024:.2f} KiB"
    return f"{value} bytes"


def load_config() -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)

    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        config.update(data)

    return config


def directory_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0

    if path.is_file():
        return path.stat().st_size

    total = 0

    for item in path.rglob("*"):
        try:
            if item.is_symlink():
                continue
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue

    return total


def build_status() -> dict[str, Any]:
    config = load_config()
    watched = []

    for rel in config.get("watched_paths", []):
        path = (ROOT / rel).resolve()
        size = directory_size_bytes(path)
        watched.append(
            {
                "path": rel,
                "absolute_path": str(path),
                "exists": path.exists(),
                "size_bytes": size,
                "size_gib": round(bytes_to_gib(size), 6),
                "size_human": format_bytes(size),
            }
        )

    total_bytes = sum(item["size_bytes"] for item in watched)

    fs_path = (ROOT / str(config.get("filesystem_path", "."))).resolve()
    if not fs_path.exists():
        fs_path = ROOT

    usage = shutil.disk_usage(fs_path)
    free_bytes = int(usage.free)

    warnings = []
    thresholds = config.get("warning_thresholds_gib", [])

    for threshold_gib in thresholds:
        threshold_bytes = int(float(threshold_gib) * 1024**3)
        if total_bytes >= threshold_bytes:
            warnings.append(
                {
                    "type": "threshold",
                    "threshold_gib": threshold_gib,
                    "message": f"Watched MEMORIA storage is above {threshold_gib} GiB.",
                }
            )

    custom = config.get("custom_warning_threshold_gib")
    if custom is not None:
        threshold_bytes = int(float(custom) * 1024**3)
        if total_bytes >= threshold_bytes:
            warnings.append(
                {
                    "type": "custom-threshold",
                    "threshold_gib": custom,
                    "message": f"Watched MEMORIA storage is above custom threshold {custom} GiB.",
                }
            )

    hard_stop_min = int(config.get("hard_stop_min_free_bytes", 524288000))
    hard_stop = free_bytes < hard_stop_min

    return {
        "schema_version": "memory-storage-watchdog-status-v0.1",
        "enabled": bool(config.get("enabled", True)),
        "config_path": str(CONFIG_PATH),
        "root": str(ROOT),
        "policy": {
            "read_only": True,
            "writes_config": False,
            "scans_private_content": False,
            "hard_stop_min_free_bytes": hard_stop_min,
        },
        "watched_paths": watched,
        "total_watched_bytes": total_bytes,
        "total_watched_gib": round(bytes_to_gib(total_bytes), 6),
        "total_watched_human": format_bytes(total_bytes),
        "filesystem": {
            "path": str(fs_path),
            "total_bytes": int(usage.total),
            "used_bytes": int(usage.used),
            "free_bytes": free_bytes,
            "free_human": format_bytes(free_bytes),
        },
        "warnings": warnings,
        "hard_stop": {
            "active": hard_stop,
            "reason": (
                "free space below hard stop minimum"
                if hard_stop
                else "free space above hard stop minimum"
            ),
            "message": (
                "STOP: filesystem free space is critically low. New storage writes must be blocked."
                if hard_stop
                else "OK: filesystem free space is sufficient."
            ),
        },
    }


def print_status(as_json: bool = False) -> int:
    status = build_status()

    if as_json:
        print(json.dumps(status, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    print("## MEMORIA MEMORY STORAGE WATCHDOG V0.1")
    print("------------------------------------------------------------")
    print("Read-only status. No config changes. No private content scanned.")
    print()
    print("Watched paths:")
    for item in status["watched_paths"]:
        print(f"- {item['path']}: {item['size_human']}")

    print()
    print(f"Total watched usage: {status['total_watched_human']}")
    print(f"Filesystem free: {status['filesystem']['free_human']}")
    print()

    if status["warnings"]:
        print("Warnings:")
        for warning in status["warnings"]:
            print(f"- WARN: {warning['message']}")
    else:
        print("Warnings: none")

    print()
    print(f"Hard stop: {'yes' if status['hard_stop']['active'] else 'no'}")
    print(status["hard_stop"]["message"])

    return 0


def command_check(args: argparse.Namespace) -> int:
    status = build_status()

    if args.json:
        print(json.dumps(status["hard_stop"], indent=2, ensure_ascii=False, sort_keys=True))

    if status["hard_stop"]["active"]:
        if not args.json:
            print("BLOCKED by Memory Storage Watchdog")
            print(status["hard_stop"]["message"])
        return 23

    if not args.json:
        print("OK Memory Storage Watchdog allows storage writes.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MEMORIA memory storage watchdog")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=lambda args: print_status(args.json))

    check = sub.add_parser("check")
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=command_check)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
