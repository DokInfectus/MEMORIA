#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import shutil
from pathlib import Path
from typing import Any


OS_RELEASE_PATH = Path("/etc/os-release")

PACKAGE_MANAGERS = (
    ("apt", "apt-get"),
    ("dnf", "dnf"),
    ("yum", "yum"),
    ("pacman", "pacman"),
    ("zypper", "zypper"),
    ("apk", "apk"),
)


def parse_os_release(path: Path = OS_RELEASE_PATH) -> dict[str, str]:
    if not path.is_file():
        return {}

    result: dict[str, str] = {}

    for raw_line in path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        value = value.strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]

        result[key.strip()] = value

    return result


def detect_package_manager() -> str | None:
    for name, command in PACKAGE_MANAGERS:
        if shutil.which(command):
            return name

    return None


def classify_platform(
    os_release: dict[str, str],
) -> dict[str, Any]:
    distro_id = os_release.get("ID", "").strip().lower()
    version_id = os_release.get("VERSION_ID", "").strip()

    if distro_id == "debian" and version_id == "13":
        return {
            "profile": "debian-13",
            "support": "TESTED / OFFICIALLY SUPPORTED",
            "package_profile_available": True,
        }

    return {
        "profile": None,
        "support": "UNKNOWN / UNSUPPORTED",
        "package_profile_available": False,
    }


def detect_platform() -> dict[str, Any]:
    os_release = parse_os_release()
    classification = classify_platform(os_release)
    package_manager = detect_package_manager()

    package_profile_available = bool(
        classification["package_profile_available"]
    )

    return {
        "schema_version": "memoria-platform-detector-v0.1",
        "pretty_name": os_release.get(
            "PRETTY_NAME",
            platform.platform(),
        ),
        "id": os_release.get("ID"),
        "id_like": os_release.get("ID_LIKE"),
        "version_id": os_release.get("VERSION_ID"),
        "version_codename": os_release.get("VERSION_CODENAME"),
        "architecture": platform.machine(),
        "package_manager": package_manager,
        "profile": classification["profile"],
        "support": classification["support"],
        "package_profile_available": package_profile_available,
        "automatic_package_installation": (
            "BLOCKED UNTIL EXPLICIT USER CONFIRMATION"
            if package_profile_available
            else "BLOCKED"
        ),
    }


def print_human(data: dict[str, Any]) -> None:
    print("MEMORIA PLATFORM DETECTOR V0.1")
    print("-" * 56)
    print(f"OS: {data['pretty_name']}")
    print(f"ID: {data['id'] or 'unknown'}")
    print(f"ID Like: {data['id_like'] or '-'}")
    print(f"Version: {data['version_id'] or 'unknown'}")
    print(f"Codename: {data['version_codename'] or '-'}")
    print(f"Architecture: {data['architecture'] or 'unknown'}")
    print(f"Package Manager: {data['package_manager'] or 'not detected'}")
    print(f"Profile: {data['profile'] or 'none'}")
    print(f"Support: {data['support']}")
    print(
        "Package Profile: "
        + (
            "AVAILABLE"
            if data["package_profile_available"]
            else "NOT AVAILABLE"
        )
    )
    print(
        "Automatic package installation: "
        f"{data['automatic_package_installation']}"
    )
    print()
    print("Read-only detection completed.")
    print("No package was installed or changed.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only MEMORIA platform detector"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    data = detect_platform()

    if args.json:
        print(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    else:
        print_human(data)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
