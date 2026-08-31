#!/usr/bin/env python3
"""
MEMORIA USB Patch Finder V0.4

Helps locate MEMORIA patch archives on USB sticks or temporary folders.

Default mode is read-only:
- scans common mount points
- lists matching patch archives
- detects mounted USB partitions
- detects unmounted USB partitions
- groups duplicate patch archives
- compares SHA256 hashes
- prefers clear USB sources over temporary working copies
- prints safe mount suggestions
- prints safe next commands

Optional:
- --copy-latest copies the recommended patch archive to /tmp

No deletion.
No config changes.
No private content inspection.
No hidden network activity.
No automatic mounting.
No automatic installation.
"""

import argparse
import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]


PATCH_PATTERNS = [
    "memoria_*patch*.tar.gz",
    "memoria_*_patch.tar.gz",
    "memoria_*patch*.zip",
    "memoria_*_patch.zip",
]

DEFAULT_SCAN_ROOTS = [
    Path("/mnt"),
    Path("/media"),
    Path("/run/media"),
    Path("/tmp"),
]

CHUNK_SIZE = 1024 * 1024


@dataclass
class UsbPartition:
    name: str
    removable: bool
    device_type: str
    mountpoint: str

    @property
    def is_partition(self) -> bool:
        return self.device_type == "part"

    @property
    def is_mounted(self) -> bool:
        return bool(self.mountpoint)

    @property
    def is_unmounted_usb_partition(self) -> bool:
        return self.removable and self.is_partition and not self.is_mounted

    @property
    def is_mounted_usb_partition(self) -> bool:
        return self.removable and self.is_partition and self.is_mounted


@dataclass
class PatchCandidate:
    path: Path
    size_bytes: int
    modified: float
    sha256: str
    source_label: str
    source_rank: int

    @property
    def size_kib(self) -> float:
        return self.size_bytes / 1024

    @property
    def short_hash(self) -> str:
        return self.sha256[:12]


@dataclass
class PatchGroup:
    name: str
    sha256: str
    items: List[PatchCandidate]

    @property
    def primary(self) -> PatchCandidate:
        return sorted(
            self.items,
            key=lambda item: (item.source_rank, -item.modified, str(item.path)),
        )[0]

    @property
    def mirrors(self) -> List[PatchCandidate]:
        primary_key = resolved_key(self.primary.path)
        return [item for item in self.items if resolved_key(item.path) != primary_key]

    @property
    def latest_modified(self) -> float:
        return max(item.modified for item in self.items)

    @property
    def short_hash(self) -> str:
        return self.sha256[:12]


def line() -> None:
    print("-" * 60)


def section(title: str) -> None:
    print()
    print(f"## {title}")
    line()


def status(label: str, message: str, ok=None) -> None:
    if ok is True:
        prefix = "OK  "
    elif ok is False:
        prefix = "FAIL"
    else:
        prefix = "INFO"

    print(f"{prefix} {label}: {message}")


def resolved_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except Exception:
        return str(path)


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def existing_scan_roots(extra_roots: Iterable[Path]) -> List[Path]:
    roots: List[Path] = []

    for root in list(DEFAULT_SCAN_ROOTS) + list(extra_roots):
        if root.exists() and root.is_dir() and root not in roots:
            roots.append(root)

    return roots


def parse_lsblk_line(line_text: str) -> Optional[UsbPartition]:
    parts = line_text.split(None, 3)

    if len(parts) < 3:
        return None

    name = parts[0]
    removable_text = parts[1]
    device_type = parts[2]
    mountpoint = parts[3].strip() if len(parts) >= 4 else ""

    return UsbPartition(
        name=name,
        removable=removable_text == "1",
        device_type=device_type,
        mountpoint=mountpoint,
    )


def detect_usb_partitions() -> List[UsbPartition]:
    try:
        result = subprocess.run(
            ["lsblk", "-rpno", "NAME,RM,TYPE,MOUNTPOINTS"],
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception:
        return []

    if result.returncode != 0:
        return []

    devices: List[UsbPartition] = []

    for line_text in result.stdout.splitlines():
        item = parse_lsblk_line(line_text)
        if item is not None:
            devices.append(item)

    return devices


def mounted_usb_roots(devices: Sequence[UsbPartition]) -> List[Path]:
    roots: List[Path] = []

    for device in devices:
        if not device.is_mounted_usb_partition:
            continue

        root = Path(device.mountpoint)
        if root.exists() and root.is_dir() and root not in roots:
            roots.append(root)

    return roots


def source_info(path: Path, usb_roots: Sequence[Path]) -> Tuple[str, int]:
    for root in usb_roots:
        if is_relative_to(path, root):
            return "usb", 0

    if is_relative_to(path, Path("/mnt")):
        return "mounted-path", 1

    if is_relative_to(path, Path("/media")):
        return "mounted-path", 1

    if is_relative_to(path, Path("/run/media")):
        return "mounted-path", 1

    if is_relative_to(path, Path("/tmp")):
        return "temporary-working-copy", 3

    return "other", 4


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)

    return digest.hexdigest()


def print_usb_devices(devices: List[UsbPartition]) -> None:
    section("USB Devices")

    if not devices:
        status("USB Devices", "none detected by lsblk", ok=None)
        return

    relevant = [
        item for item in devices
        if item.removable and item.device_type in {"disk", "part"}
    ]

    if not relevant:
        status("USB Devices", "no removable disk or partition detected", ok=None)
        return

    for item in relevant:
        if item.device_type == "disk":
            status("USB Disk", item.name, ok=True)
        elif item.is_mounted_usb_partition:
            status("Mounted USB Partition", f"{item.name} -> {item.mountpoint}", ok=True)
        elif item.is_unmounted_usb_partition:
            status("Unmounted USB Partition", item.name, ok=None)
            print("     Suggested manual mount:")
            print("       mkdir -p /mnt/usb")
            print(f"       mount {item.name} /mnt/usb")
        else:
            status("USB Partition", f"{item.name} -> {item.mountpoint or 'not mounted'}", ok=None)


def find_candidates(roots: Iterable[Path], usb_roots: Sequence[Path]) -> List[PatchCandidate]:
    candidates: List[PatchCandidate] = []

    for root in roots:
        for pattern in PATCH_PATTERNS:
            try:
                matches = root.rglob(pattern)
            except Exception:
                continue

            for path in matches:
                try:
                    if not path.is_file():
                        continue

                    stat = path.stat()
                    label, rank = source_info(path, usb_roots)
                    candidates.append(
                        PatchCandidate(
                            path=path,
                            size_bytes=stat.st_size,
                            modified=stat.st_mtime,
                            sha256=sha256_file(path),
                            source_label=label,
                            source_rank=rank,
                        )
                    )
                except Exception:
                    continue

    candidates.sort(key=lambda item: item.modified, reverse=True)

    seen = set()
    unique: List[PatchCandidate] = []

    for item in candidates:
        key = resolved_key(item.path)

        if key in seen:
            continue

        seen.add(key)
        unique.append(item)

    return unique


def group_candidates(candidates: Sequence[PatchCandidate]) -> List[PatchGroup]:
    grouped: Dict[Tuple[str, str], List[PatchCandidate]] = {}

    for item in candidates:
        grouped.setdefault((item.path.name, item.sha256), []).append(item)

    groups = [
        PatchGroup(name=name, sha256=sha256, items=items)
        for (name, sha256), items in grouped.items()
    ]

    groups.sort(
        key=lambda group: (
            -group.latest_modified,
            group.primary.source_rank,
            group.name,
        )
    )

    return groups


def hash_conflicts(groups: Sequence[PatchGroup]) -> Dict[str, List[PatchGroup]]:
    by_name: Dict[str, List[PatchGroup]] = {}

    for group in groups:
        by_name.setdefault(group.name, []).append(group)

    return {
        name: variants
        for name, variants in by_name.items()
        if len({group.sha256 for group in variants}) > 1
    }


def copy_latest(groups: Sequence[PatchGroup], target_dir: Path) -> Path:
    if not groups:
        raise RuntimeError("no patch candidates found")

    target_dir.mkdir(parents=True, exist_ok=True)

    source = groups[0].primary.path
    target = target_dir / source.name

    if resolved_key(source) == resolved_key(target):
        status("Copy Latest", f"source already in {target_dir}; no copy needed", ok=True)
        return target

    shutil.copy2(source, target)
    status("Copy Latest", f"{source} -> {target}", ok=True)

    return target


def print_grouped_candidates(groups: Sequence[PatchGroup]) -> None:
    section("Patch Archives")

    if not groups:
        status("Patch Archives", "none found", ok=False)
        return

    for index, group in enumerate(groups, start=1):
        primary = group.primary
        marker = "latest" if index == 1 else "found"
        mirror_count = len(group.mirrors)
        mirror_text = f", mirrors={mirror_count}" if mirror_count else ""

        status(
            f"{index}",
            f"{group.name} ({primary.size_kib:.1f} KiB, sha256={group.short_hash}, primary={primary.source_label}{mirror_text}, {marker})",
            ok=True,
        )
        print(f"     Primary: {primary.path}")

        for mirror in group.mirrors:
            print(f"     Mirror : {mirror.path} ({mirror.source_label})")


def print_hash_conflicts(conflicts: Dict[str, List[PatchGroup]]) -> None:
    section("Hash Comparison")

    if not conflicts:
        status("SHA256", "no same-name hash conflicts detected", ok=True)
        return

    for name, variants in conflicts.items():
        status("Hash Conflict", f"{name}: {len(variants)} different SHA256 values", ok=False)

        for group in variants:
            primary = group.primary
            print(f"     sha256={group.sha256}")
            print(f"     primary={primary.path}")

    print()
    print("Do not apply a conflicting same-name patch until the source is verified.")


def print_next_steps(groups: Sequence[PatchGroup], devices: Sequence[UsbPartition], conflicts: Dict[str, List[PatchGroup]]) -> None:
    section("Next Steps")

    if not groups:
        status("USB Patch Finder", "copy the patch archive to the USB stick and run this tool again", ok=None)

        unmounted = [item for item in devices if item.is_unmounted_usb_partition]
        if unmounted:
            print()
            print("Unmounted USB device detected.")
            print("Mount it manually, then run this tool again:")
            print()
            print("  mkdir -p /mnt/usb")
            print(f"  mount {unmounted[0].name} /mnt/usb")
            print("  python3 tools/memoria_usb_patch_finder.py")

        return

    latest = groups[0]
    primary = latest.primary

    status("Recommended Patch", latest.name, ok=True)
    status("Primary Source", str(primary.path), ok=True)
    status("SHA256", latest.sha256, ok=True)

    if latest.name in conflicts:
        status("Warning", "same patch name has multiple SHA256 values; verify before applying", ok=False)

    if latest.mirrors:
        print()
        print("Mirrors with identical SHA256:")
        for mirror in latest.mirrors:
            print(f"  - {mirror.path} ({mirror.source_label})")

    print()
    print("Safe manual apply example:")
    print()
    print("  cd /tmp")
    if is_relative_to(primary.path, Path("/tmp")):
        print("  # patch is already in /tmp; no copy step needed")
    else:
        print(f"  cp '{primary.path}' /tmp/")
    print(f"  tar -xzf '{latest.name}'")
    print(f"  cd {latest.name.replace('.tar.gz', '').replace('.zip', '')}")
    print(f"  bash apply_patch.sh '{PROJECT_ROOT}'")
    print()
    print("Optional helper copy:")
    print()
    print("  python3 tools/memoria_usb_patch_finder.py --copy-latest")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find MEMORIA patch archives on USB sticks and common temp folders."
    )
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        help="Additional scan root. Can be used multiple times.",
    )
    parser.add_argument(
        "--copy-latest",
        action="store_true",
        help="Copy recommended patch archive to /tmp.",
    )
    parser.add_argument(
        "--target-dir",
        default="/tmp",
        help="Target directory for --copy-latest. Default: /tmp",
    )

    args = parser.parse_args()

    extra_roots = [Path(item) for item in args.root]
    devices = detect_usb_partitions()
    usb_roots = mounted_usb_roots(devices)
    roots = existing_scan_roots(extra_roots)

    print("MEMORIA USB PATCH FINDER V0.4")
    line()
    print("Finds MEMORIA patch archives on USB/temp paths.")
    print("Default mode is read-only. No deletion. No config changes.")
    print("Duplicates are grouped by filename and SHA256 hash.")
    print("Unmounted USB devices are detected, but not mounted automatically.")
    line()

    print_usb_devices(devices)

    section("Scan Roots")

    for root in roots:
        status("Scan Root", str(root), ok=True)

    candidates = find_candidates(roots, usb_roots)
    groups = group_candidates(candidates)
    conflicts = hash_conflicts(groups)

    print_grouped_candidates(groups)
    print_hash_conflicts(conflicts)

    if args.copy_latest:
        section("Copy Latest")

        try:
            copied = copy_latest(groups, Path(args.target_dir))
            status("Patch Ready", str(copied), ok=True)
        except Exception as exc:
            status("Copy", str(exc), ok=False)
            return 1

    print_next_steps(groups, devices, conflicts)

    section("Result")
    status("USB Patch Finder", "completed", ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

