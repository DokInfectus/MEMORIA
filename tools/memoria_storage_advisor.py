#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HIDDEN_FSTYPES = {
    "tmpfs",
    "devtmpfs",
    "overlay",
    "squashfs",
    "proc",
    "sysfs",
    "cgroup",
    "cgroup2",
    "devpts",
    "securityfs",
    "pstore",
    "bpf",
    "autofs",
    "mqueue",
    "debugfs",
    "tracefs",
    "configfs",
    "fusectl",
    "efivarfs",
    "ramfs",
}

SYSTEM_MOUNTPOINTS = {
    "/",
    "/boot",
    "/boot/efi",
    "/efi",
    "/run",
    "/tmp",
    "/dev",
    "/dev/shm",
    "/proc",
    "/sys",
    "/var/lib/docker",
    "/var/lib/containerd",
}

REAL_STORAGE_FSTYPES = {
    "ext4",
    "xfs",
    "btrfs",
    "zfs",
    "f2fs",
}


@dataclass
class FilesystemInfo:
    filesystem: str
    fstype: str
    size_bytes: int
    used_bytes: int
    available_bytes: int
    capacity: str
    mountpoint: str


def gib(value: int) -> float:
    return value / 1024 / 1024 / 1024


def parse_df_output(text: str) -> list[FilesystemInfo]:
    rows: list[FilesystemInfo] = []

    for line in text.splitlines()[1:]:
        parts = line.split(maxsplit=6)
        if len(parts) < 7:
            continue

        filesystem, fstype, size, used, available, capacity, mountpoint = parts

        try:
            rows.append(
                FilesystemInfo(
                    filesystem=filesystem,
                    fstype=fstype,
                    size_bytes=int(size),
                    used_bytes=int(used),
                    available_bytes=int(available),
                    capacity=capacity,
                    mountpoint=mountpoint,
                )
            )
        except ValueError:
            continue

    return rows


def is_hidden_runtime(fs: FilesystemInfo) -> tuple[bool, str]:
    mp = fs.mountpoint

    if fs.fstype in HIDDEN_FSTYPES:
        return True, f"runtime filesystem: {fs.fstype}"

    if mp in SYSTEM_MOUNTPOINTS and mp != "/":
        return True, f"system/runtime mountpoint: {mp}"

    if mp.startswith("/run/"):
        return True, "runtime mount under /run"

    if mp.startswith("/dev/"):
        return True, "device/runtime mount under /dev"

    if mp.startswith("/sys/"):
        return True, "kernel/runtime mount under /sys"

    if mp.startswith("/proc/"):
        return True, "kernel/runtime mount under /proc"

    if "/docker/" in mp or "/containerd/" in mp or "overlay" in mp.lower():
        return True, "container overlay/runtime storage"

    if fs.fstype in {"vfat", "efi"} or "efi" in mp.lower():
        return True, "EFI/boot partition"

    return False, ""


def classify_filesystem(fs: FilesystemInfo, device: dict | None = None) -> dict:
    hidden, reason = is_hidden_runtime(fs)
    removable_risk = removable_storage_warning(device)

    if hidden:
        return {
            "visible": False,
            "role": "hidden-runtime",
            "reason": reason,
            "filesystem": fs.filesystem,
            "fstype": fs.fstype,
            "mountpoint": fs.mountpoint,
            "size_gib": round(gib(fs.size_bytes), 2),
            "available_gib": round(gib(fs.available_bytes), 2),
        }

    if fs.fstype not in REAL_STORAGE_FSTYPES:
        return {
            "visible": False,
            "role": "unsupported-filesystem",
            "reason": f"filesystem type not recommended for memory storage: {fs.fstype}",
            "filesystem": fs.filesystem,
            "fstype": fs.fstype,
            "mountpoint": fs.mountpoint,
            "size_gib": round(gib(fs.size_bytes), 2),
            "available_gib": round(gib(fs.available_bytes), 2),
        }

    role = "candidate"
    reason = "usable mounted storage"

    if fs.mountpoint == "/":
        role = "system-root-caution"
        reason = "root filesystem; usable only with conservative budget"

    safe_budget = min(int(fs.available_bytes * 0.01), 1 * 1024**3)
    normal_budget = min(int(fs.available_bytes * 0.02), 5 * 1024**3)
    large_budget = min(int(fs.available_bytes * 0.05), 20 * 1024**3)

    if removable_risk["removable"] and role == "candidate":
        role = "removable-candidate"
        reason = "usable mounted removable storage; extra confirmation required"

    return {
        "visible": True,
        "role": role,
        "reason": reason,
        "filesystem": fs.filesystem,
        "fstype": fs.fstype,
        "mountpoint": fs.mountpoint,
        "size_gib": round(gib(fs.size_bytes), 2),
        "available_gib": round(gib(fs.available_bytes), 2),
        "requires_extra_confirmation": removable_risk["requires_extra_confirmation"],
        "removable_storage": removable_risk,
        "suggested_budgets": {
            "safe_gib": round(gib(safe_budget), 2),
            "normal_gib": round(gib(normal_budget), 2),
            "large_gib": round(gib(large_budget), 2),
            "min_free_gib": 10,
        },
    }



def flatten_lsblk_nodes(nodes: list[dict]) -> list[dict]:
    flattened: list[dict] = []

    for node in nodes:
        flattened.append(node)
        children = node.get("children") or []
        flattened.extend(flatten_lsblk_nodes(children))

    return flattened


def collect_lsblk_mount_index() -> dict[str, dict]:
    result = subprocess.run(
        [
            "lsblk",
            "-J",
            "-b",
            "-o",
            "NAME,PATH,TYPE,FSTYPE,SIZE,MOUNTPOINTS,MODEL,TRAN,RM,HOTPLUG",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
    )

    if result.returncode != 0:
        return {}

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}

    mount_index: dict[str, dict] = {}

    for node in flatten_lsblk_nodes(data.get("blockdevices", [])):
        mountpoints = node.get("mountpoints") or []
        for mountpoint in mountpoints:
            if mountpoint:
                mount_index[str(mountpoint)] = node

    return mount_index


def removable_storage_warning(device: dict | None) -> dict:
    if not device:
        return {
            "removable": False,
            "requires_extra_confirmation": False,
            "warning": "",
        }

    transport = str(device.get("tran") or "").lower()
    removable = bool(device.get("rm")) or bool(device.get("hotplug")) or transport == "usb"

    if not removable:
        return {
            "removable": False,
            "requires_extra_confirmation": False,
            "warning": "",
        }

    return {
        "removable": True,
        "requires_extra_confirmation": True,
        "warning": (
            "USB/removable storage detected. Use only if you understand that "
            "memories stored on this device may be unavailable or lost if the "
            "device is removed, defective, lost, or not mounted. Keep backups."
        ),
        "transport": transport,
        "device_path": device.get("path"),
        "device_model": device.get("model"),
    }



def collect_lsblk_nodes() -> list[dict]:
    result = subprocess.run(
        [
            "lsblk",
            "-J",
            "-b",
            "-o",
            "NAME,PATH,TYPE,FSTYPE,SIZE,MOUNTPOINTS,MODEL,TRAN,RM,HOTPLUG",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
    )

    if result.returncode != 0:
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    return flatten_lsblk_nodes(data.get("blockdevices", []))


def node_mountpoints(node: dict) -> list[str]:
    mountpoints = node.get("mountpoints") or []

    if isinstance(mountpoints, str):
        mountpoints = [mountpoints]

    return [str(item) for item in mountpoints if item]



SYSTEM_CRITICAL_MOUNTPOINTS = {
    "/",
    "/boot",
    "/boot/efi",
    "/efi",
    "[SWAP]",
}


def node_display_name(node: dict) -> str:
    path = str(node.get("path") or "")
    if path.startswith("/dev/"):
        return path.removeprefix("/dev/")
    return str(node.get("name") or path)


def node_has_system_critical_child(node: dict) -> tuple[bool, str]:
    mountpoints = node_mountpoints(node)
    fstype = str(node.get("fstype") or "").lower()

    for mountpoint in mountpoints:
        if mountpoint in SYSTEM_CRITICAL_MOUNTPOINTS:
            return True, f"critical mountpoint detected: {mountpoint}"
        if "efi" in mountpoint.lower():
            return True, f"EFI mountpoint detected: {mountpoint}"

    if fstype == "swap":
        return True, "swap partition detected"

    for child in node.get("children") or []:
        critical, reason = node_has_system_critical_child(child)
        if critical:
            return True, reason

    return False, ""


def destructive_action_safety_gate(node: dict, typed_confirmation: str = "") -> dict:
    expected = node_display_name(node)
    path = str(node.get("path") or f"/dev/{expected}")

    critical, reason = node_has_system_critical_child(node)
    if critical:
        return {
            "allowed": False,
            "decision": "abort-system-disk",
            "path": path,
            "expected_confirmation": expected,
            "reason": reason,
            "message": (
                "ABORT: system/master disk detected. This target or its children "
                "contain root, boot, EFI, swap, or another critical system mount. "
                "MEMORIA will not format or destructively modify it."
            ),
        }

    if typed_confirmation and typed_confirmation.strip() != expected:
        return {
            "allowed": False,
            "decision": "abort-confirmation-mismatch",
            "path": path,
            "expected_confirmation": expected,
            "reason": "typed confirmation does not match selected target",
            "message": (
                f"ABORT: confirmation mismatch. To continue, the user must type "
                f"exactly: {expected}"
            ),
        }

    return {
        "allowed": True,
        "decision": "confirmation-required" if not typed_confirmation else "confirmed",
        "path": path,
        "expected_confirmation": expected,
        "reason": "no system-critical mountpoints detected",
        "message": (
            f"Before destructive setup, type exactly '{expected}'. "
            "Formatting will erase ALL data on the selected target."
        ),
    }


def classify_unmounted_block_node(node: dict) -> dict | None:
    node_type = str(node.get("type") or "").lower()
    fstype = str(node.get("fstype") or "").strip()
    mountpoints = node_mountpoints(node)
    children = node.get("children") or []
    path = node.get("path") or ("/dev/" + str(node.get("name") or ""))

    if node_type not in {"disk", "part"}:
        return None

    if mountpoints:
        return None

    # Do not propose formatting a whole disk that already has partitions.
    if node_type == "disk" and children:
        return None

    # V0.2 only suggests formatting truly unformatted targets.
    # Existing filesystems need a later mount/import workflow, not a format suggestion.
    if fstype:
        return None

    if not str(path).startswith("/dev/"):
        return None

    try:
        size_bytes = int(node.get("size") or 0)
    except ValueError:
        size_bytes = 0

    if size_bytes <= 0:
        return None

    removable_risk = removable_storage_warning(node)
    safety_gate = destructive_action_safety_gate(node)
    role = "unformatted-format-candidate"

    if removable_risk["removable"]:
        role = "unformatted-removable-format-candidate"

    return {
        "visible": True,
        "role": role,
        "path": path,
        "device_type": node_type,
        "fstype": "",
        "size_gib": round(gib(size_bytes), 2),
        "model": node.get("model"),
        "transport": node.get("tran"),
        "suggested_filesystem": "ext4",
        "requires_destructive_format_confirmation": True,
        "destructive_safety_gate": safety_gate,
        "required_confirmation_text": safety_gate["expected_confirmation"],
        "destructive_warning": (
            "Formatting this target as ext4 will erase ALL data on the selected "
            "device or partition. Continue only after explicit user confirmation. "
            "If a system/root/boot/EFI/swap target is detected, MEMORIA aborts."
        ),
        "removable_storage": removable_risk,
    }


def discover_format_candidates(nodes: list[dict]) -> list[dict]:
    candidates: list[dict] = []

    for node in nodes:
        candidate = classify_unmounted_block_node(node)
        if candidate:
            candidates.append(candidate)

    return candidates


def collect_df() -> list[FilesystemInfo]:
    result = subprocess.run(
        ["df", "-PT", "-B1"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout)
    return parse_df_output(result.stdout)


def current_memoria_usage() -> dict:
    paths = [
        "knowledge",
        "knowledge/memory",
        "knowledge/memory_candidates",
        "conversations",
        "summaries",
        "logs",
    ]

    usage = {}
    for rel in paths:
        path = ROOT / rel
        if not path.exists():
            usage[rel] = 0
            continue

        total = 0
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
        usage[rel] = total

    return usage


def command_scan(args: argparse.Namespace) -> int:
    rows = collect_df()
    lsblk_nodes = collect_lsblk_nodes()
    mount_index = collect_lsblk_mount_index()
    classified = [classify_filesystem(row, mount_index.get(row.mountpoint)) for row in rows]
    format_candidates = discover_format_candidates(lsblk_nodes)

    visible = [item for item in classified if item["visible"]]
    hidden = [item for item in classified if not item["visible"]]

    if args.json:
        print(json.dumps({
            "version": "storage-advisor-v0.3",
            "policy": {
                "read_only": True,
                "writes_config": False,
                "changes_mounts": False,
                "scans_private_content": False,
            },
            "visible_candidates": visible,
            "hidden_runtime": hidden,
            "format_candidates": format_candidates,
            "memoria_usage_bytes": current_memoria_usage(),
        }, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    print("## MEMORIA STORAGE ADVISOR V0.3")
    print("------------------------------------------------------------")
    print("Read-only scan. No config changes. No mounts changed. No private content scanned.")
    print()

    print("Recommended storage candidates:")
    if not visible:
        print("INFO No recommended storage candidates found.")
    else:
        for index, item in enumerate(visible, start=1):
            budgets = item["suggested_budgets"]
            print(
                f"{index}) {item['mountpoint']} | {item['fstype']} | "
                f"size={item['size_gib']} GiB | free={item['available_gib']} GiB | "
                f"role={item['role']}"
            )
            print(f"   Reason: {item['reason']}")
            if item.get("requires_extra_confirmation"):
                print("   WARNING: USB/removable storage detected.")
                print("   WARNING: If this device is removed, defective, lost, or not mounted,")
                print("            memories stored there may be unavailable or lost without backup.")
                print("   WARNING: Extra confirmation is required before using this target.")
            print(
                f"   Suggested: safe={budgets['safe_gib']} GiB, "
                f"normal={budgets['normal_gib']} GiB, large={budgets['large_gib']} GiB, "
                f"keep-free={budgets['min_free_gib']} GiB"
            )

    print()
    print("Unformatted storage targets that may need setup:")
    if not format_candidates:
        print("INFO No unformatted storage targets found.")
    else:
        for index, item in enumerate(format_candidates, start=1):
            print(
                f"{index}) {item['path']} | type={item['device_type']} | "
                f"size={item['size_gib']} GiB | suggested_fs={item['suggested_filesystem']} | "
                f"role={item['role']}"
            )
            print("   WARNING: Formatting this target as ext4 will erase ALL data on it.")
            print("   WARNING: MEMORIA will require explicit yes/no confirmation before formatting.")
            print(f"   REQUIRED: User must type exactly: {item['required_confirmation_text']}")
            print(f"   SAFETY: {item['destructive_safety_gate']['message']}")
            if item.get("removable_storage", {}).get("removable"):
                print("   WARNING: USB/removable target detected; memories may be unavailable or lost")
                print("            if the device is removed, defective, lost, or not mounted.")

    if args.show_hidden:
        print()
        print("Hidden runtime/system mounts:")
        for item in hidden:
            print(
                f"- {item['mountpoint']} | {item['fstype']} | "
                f"role={item['role']} | reason={item['reason']}"
            )

    print()
    print("Current MEMORIA storage usage:")
    for rel, size in current_memoria_usage().items():
        print(f"- {rel}: {size} bytes")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MEMORIA read-only storage advisor")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan")
    scan.add_argument("--json", action="store_true")
    scan.add_argument("--show-hidden", action="store_true")
    scan.set_defaults(func=command_scan)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
