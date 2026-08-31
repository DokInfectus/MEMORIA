#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(
    os.environ.get(
        "MEMORIA_STORAGE_LOCATION_CONFIG",
        str(PROJECT_ROOT / "config" / "memory_storage_location.json"),
    )
)

DEFAULT_CONFIG = {
    "schema_version": "memory-storage-location-v0.1",
    "storage_root": ".",
    "mode": "project-local",
    "selected_by": "default",
    "reason": "Default MEMORIA storage location inside project directory.",
    "managed_paths": {
        "memory": "knowledge/memory",
        "memory_candidates": "knowledge/memory_candidates",
        "conversations": "conversations",
        "summaries": "summaries",
        "logs": "logs",
        "imports": "imports",
        "attachments": "attachments",
    },
}

BLOCKED_STORAGE_ROOTS = {
    "/",
    "/boot",
    "/boot/efi",
    "/efi",
    "/run",
    "/tmp",
    "/dev",
    "/proc",
    "/sys",
    "/var/lib/docker",
    "/var/lib/containerd",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config() -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)

    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        config.update(data)

        managed = dict(DEFAULT_CONFIG["managed_paths"])
        managed.update(data.get("managed_paths", {}))
        config["managed_paths"] = managed

    return config


def resolve_storage_root(config: dict[str, Any] | None = None) -> Path:
    config = config or load_config()
    root_text = str(config.get("storage_root", "."))

    root = Path(root_text)
    if not root.is_absolute():
        root = PROJECT_ROOT / root

    return root.resolve()


def active_storage_root() -> Path:
    return resolve_storage_root(load_config())


def managed_paths(config: dict[str, Any] | None = None) -> dict[str, Path]:
    config = config or load_config()
    root = resolve_storage_root(config)

    result = {}
    for name, rel in config.get("managed_paths", {}).items():
        result[name] = (root / rel).resolve()

    return result


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


def bytes_human(value: int) -> str:
    if value >= 1024**3:
        return f"{value / 1024**3:.2f} GiB"
    if value >= 1024**2:
        return f"{value / 1024**2:.2f} MiB"
    if value >= 1024:
        return f"{value / 1024:.2f} KiB"
    return f"{value} bytes"


def validate_storage_root(root: Path) -> tuple[bool, str]:
    resolved = root.resolve()
    resolved_text = str(resolved)

    if resolved_text in BLOCKED_STORAGE_ROOTS:
        return False, f"blocked system/runtime path: {resolved_text}"

    if resolved_text.startswith("/run/"):
        return False, "blocked runtime path under /run"

    if resolved_text.startswith("/dev/"):
        return False, "blocked device path under /dev"

    if resolved_text.startswith("/proc/"):
        return False, "blocked kernel path under /proc"

    if resolved_text.startswith("/sys/"):
        return False, "blocked kernel path under /sys"

    if "/docker/" in resolved_text or "/containerd/" in resolved_text:
        return False, "blocked container runtime path"

    if not resolved.exists():
        return False, "storage root does not exist yet; create/mount it explicitly first"

    if not resolved.is_dir():
        return False, "storage root is not a directory"

    return True, "storage root looks selectable"


def build_status() -> dict[str, Any]:
    config = load_config()
    root = resolve_storage_root(config)
    paths = managed_paths(config)

    path_status = []
    total = 0

    for name, path in paths.items():
        size = directory_size_bytes(path)
        total += size
        path_status.append(
            {
                "name": name,
                "path": str(path),
                "exists": path.exists(),
                "size_bytes": size,
                "size_human": bytes_human(size),
            }
        )

    fs_target = root if root.exists() else PROJECT_ROOT
    usage = shutil.disk_usage(fs_target)

    valid, reason = validate_storage_root(root) if root.exists() else (False, "storage root does not exist")

    return {
        "schema_version": "memory-storage-manager-status-v0.1",
        "config_path": str(CONFIG_PATH),
        "project_root": str(PROJECT_ROOT),
        "storage_root": str(root),
        "mode": config.get("mode"),
        "valid_storage_root": valid,
        "validation_reason": reason,
        "managed_paths": path_status,
        "total_managed_bytes": total,
        "total_managed_human": bytes_human(total),
        "filesystem": {
            "path": str(fs_target),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "free_human": bytes_human(usage.free),
        },
        "policy": {
            "does_not_format": True,
            "does_not_mount": True,
            "does_not_move_data": True,
            "selection_requires_exact_confirmation": True,
        },
    }


def save_selection(root: Path, reason: str, selected_by: str = "memoria_memory_storage_manager.py") -> dict[str, Any]:
    resolved = root.resolve()
    valid, validation_reason = validate_storage_root(resolved)

    if not valid:
        raise SystemExit(f"ABORT storage root rejected: {validation_reason}")

    current = load_config()
    data = {
        "schema_version": "memory-storage-location-v0.1",
        "storage_root": str(resolved),
        "mode": "external-selected" if resolved != PROJECT_ROOT else "project-local",
        "selected_at": now_iso(),
        "selected_by": selected_by,
        "reason": reason,
        "managed_paths": current.get("managed_paths", DEFAULT_CONFIG["managed_paths"]),
    }

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return build_status()


def print_status(as_json: bool = False) -> int:
    status = build_status()

    if as_json:
        print(json.dumps(status, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    print("## MEMORIA MEMORY STORAGE MANAGER V0.1")
    print("------------------------------------------------------------")
    print("No formatting. No mounting. No data migration in this step.")
    print()
    print(f"Storage root: {status['storage_root']}")
    print(f"Mode: {status['mode']}")
    print(f"Valid: {'yes' if status['valid_storage_root'] else 'no'}")
    print(f"Reason: {status['validation_reason']}")
    print()
    print("Managed paths:")
    for item in status["managed_paths"]:
        print(f"- {item['name']}: {item['path']} | {item['size_human']} | exists={'yes' if item['exists'] else 'no'}")

    print()
    print(f"Total managed usage: {status['total_managed_human']}")
    print(f"Filesystem free: {status['filesystem']['free_human']}")
    return 0


def command_select(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    expected = str(root)

    if args.confirm != expected:
        print("ABORT: confirmation mismatch.")
        print(f"To select this storage root, type exactly: {expected}")
        return 23

    status = save_selection(root, args.reason or "Explicit storage root selection.")
    print("OK memory storage root selected")
    print(f"Storage root: {status['storage_root']}")
    print("NOTE: This does not move existing data.")
    print("NOTE: Writer integration/migration must be done in separate safe steps.")
    return 0


def command_path_for(args: argparse.Namespace) -> int:
    paths = managed_paths()

    if args.name not in paths:
        print(f"Unknown managed path: {args.name}")
        print("Known paths: " + ", ".join(sorted(paths)))
        return 2

    print(paths[args.name])
    return 0



MIGRATION_MANAGED_RELS = [
    "knowledge/memory",
    "knowledge/memory_candidates",
    "conversations",
    "summaries",
    "logs",
    "imports",
]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_for(root: Path, rels: list[str]) -> dict[str, str]:
    manifest: dict[str, str] = {}

    for rel in rels:
        base = root / rel
        base.mkdir(parents=True, exist_ok=True)

        for file in sorted(base.rglob("*")):
            if file.is_file() and not file.is_symlink():
                manifest[str(file.relative_to(root))] = _sha256_file(file)

    return manifest


def _write_manifest(path: Path, manifest: dict[str, str]) -> None:
    lines = [f"{sha}  {rel}\n" for rel, sha in sorted(manifest.items())]
    path.write_text("".join(lines), encoding="utf-8")


def _runtime_mode_json() -> dict[str, Any]:
    tool = PROJECT_ROOT / "tools" / "memoria_runtime_mode.py"
    result = subprocess.run(
        [sys.executable, str(tool), "status", "--json"],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        return {"mode": "NORMAL", "error": result.stdout}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"mode": "NORMAL", "error": result.stdout}


def _set_runtime_mode(mode: str, reason: str) -> None:
    tool = PROJECT_ROOT / "tools" / "memoria_runtime_mode.py"
    subprocess.run(
        [sys.executable, str(tool), "set", mode, "--reason", reason],
        cwd=PROJECT_ROOT,
        text=True,
        check=False,
    )


def _copy_managed_files(src_root: Path, dst_root: Path, rels: list[str]) -> int:
    copied = 0

    for rel in rels:
        src_base = src_root / rel
        dst_base = dst_root / rel
        src_base.mkdir(parents=True, exist_ok=True)
        dst_base.mkdir(parents=True, exist_ok=True)

        for src in sorted(src_base.rglob("*")):
            if not src.is_file() or src.is_symlink():
                continue

            dst = dst_root / src.relative_to(src_root)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1

    return copied


def _delete_managed_source_files(src_root: Path, manifest: dict[str, str]) -> int:
    deleted = 0

    for rel in sorted(manifest):
        src = src_root / rel
        if src.exists() and src.is_file():
            src.unlink()
            deleted += 1

    for rel in MIGRATION_MANAGED_RELS:
        base = src_root / rel
        if base.exists():
            for directory in sorted([x for x in base.rglob("*") if x.is_dir()], reverse=True):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            base.mkdir(parents=True, exist_ok=True)

    return deleted


def command_migrate_from_project(args: argparse.Namespace) -> int:
    src_root = PROJECT_ROOT.resolve()
    dst_root = active_storage_root().resolve()

    if src_root == dst_root:
        print("ABORT: selected storage root is still project-local; nothing to migrate.")
        return 23

    valid, reason = validate_storage_root(dst_root)
    if not valid:
        print(f"ABORT: selected storage root rejected: {reason}")
        return 23

    if not Path("/proc/mounts").exists():
        print("ABORT: cannot verify mounts on this system.")
        return 23

    if not shutil.disk_usage(dst_root).free > 0:
        print("ABORT: destination filesystem reports no free space.")
        return 23

    expected = "COPY_CHECKSUM_DELETE_SOURCE"
    if args.confirm != expected:
        print("ABORT: confirmation mismatch.")
        print(f"To migrate and delete source files after checksum pass, type exactly: {expected}")
        return 23

    work = PROJECT_ROOT / f"memory_migration_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    work.mkdir(parents=True, exist_ok=True)

    print("MEMORIA STORAGE MIGRATION V0.1")
    print(f"Source:      {src_root}")
    print(f"Destination: {dst_root}")
    print(f"Workdir:     {work}")
    print("Mode: copy -> checksum compare -> delete source")
    print()

    previous_mode = _runtime_mode_json().get("mode", "NORMAL")
    _set_runtime_mode("SERVICE_STOP", "Memory migration to selected storage root")

    try:
        print("Building source manifest...")
        source_manifest = _manifest_for(src_root, MIGRATION_MANAGED_RELS)
        _write_manifest(work / "source.sha256", source_manifest)
        print(f"Source files: {len(source_manifest)}")

        if args.dry_run:
            print("DRY RUN: no files copied and no source files deleted.")
            _set_runtime_mode(previous_mode, "Dry-run migration completed; restoring previous runtime mode")
            return 0

        print("Copying files to selected storage root...")
        copied = _copy_managed_files(src_root, dst_root, MIGRATION_MANAGED_RELS)
        print(f"Copied files: {copied}")
        sync = getattr(os, "sync", None)
        if sync:
            sync()

        print("Building target manifest...")
        target_manifest = _manifest_for(dst_root, MIGRATION_MANAGED_RELS)
        _write_manifest(work / "target.sha256", target_manifest)
        print(f"Target files: {len(target_manifest)}")

        if source_manifest != target_manifest:
            diff_path = work / "checksum_mismatch.txt"
            diff_path.write_text(
                json.dumps(
                    {
                        "missing_or_changed": sorted(
                            rel for rel, sha in source_manifest.items()
                            if target_manifest.get(rel) != sha
                        ),
                        "extra_target_files": sorted(
                            rel for rel in target_manifest
                            if rel not in source_manifest
                        ),
                    },
                    indent=2,
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )
            print("ABORT: checksum mismatch. Source was NOT deleted.")
            print(f"Inspect: {diff_path}")
            return 23

        print("Checksum PASS.")
        deleted = _delete_managed_source_files(src_root, source_manifest)
        if sync:
            sync()

        print(f"Deleted source files after verified copy: {deleted}")
        print("OK MEMORIA storage migration completed.")
        print(f"Manifest: {work / 'source.sha256'}")
        return 0

    finally:
        _set_runtime_mode(previous_mode, "Memory migration finished; restoring previous runtime mode")

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MEMORIA memory storage manager")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=lambda args: print_status(args.json))

    select = sub.add_parser("select")
    select.add_argument("--root", required=True)
    select.add_argument("--confirm", required=True)
    select.add_argument("--reason", default="")
    select.set_defaults(func=command_select)

    path_for = sub.add_parser("path-for")
    path_for.add_argument("name")
    path_for.set_defaults(func=command_path_for)

    migrate = sub.add_parser("migrate-from-project")
    migrate.add_argument("--confirm", required=True)
    migrate.add_argument("--dry-run", action="store_true")
    migrate.set_defaults(func=command_migrate_from_project)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
