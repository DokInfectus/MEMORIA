#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

from memoria_package_profile import build_plan


SCHEMA_VERSION = "memoria-package-satisfaction-v0.1"

DPKG_STATUS_PATH = Path("/var/lib/dpkg/status")

APPLICABLE_FEATURES = frozenset({
    "local-ocr",
    "matrix-ui+ocr",
})


def parse_installed_packages(
    path: Path = DPKG_STATUS_PATH,
) -> set[str]:
    if not path.is_file():
        raise RuntimeError("dpkg status file unavailable")

    text = path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    installed: set[str] = set()
    seen_packages: set[str] = set()
    package_records = 0

    for stanza in text.split("\n\n"):
        package = None
        status = None

        for raw_line in stanza.splitlines():
            if raw_line.startswith("Package: "):
                if package is not None:
                    raise RuntimeError(
                        "duplicate Package field"
                    )
                package = raw_line[9:].strip()
            elif raw_line.startswith("Status: "):
                if status is not None:
                    raise RuntimeError(
                        "duplicate Status field"
                    )
                status = raw_line[8:].strip()

        if package is None:
            continue

        if not package:
            raise RuntimeError("empty Package field")

        if status is None or len(status.split()) != 3:
            raise RuntimeError(
                "invalid or missing Status field"
            )

        if package in seen_packages:
            raise RuntimeError(
                "duplicate package record"
            )

        seen_packages.add(package)
        package_records += 1

        if status == "install ok installed":
            installed.add(package)

    if package_records == 0:
        raise RuntimeError(
            "dpkg status contains no package records"
        )

    return installed


def evaluate_package_satisfaction(
    feature_profile: str,
    *,
    status_path: Path = DPKG_STATUS_PATH,
    platform_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "feature_profile": feature_profile,
        "satisfaction_status": "NOT APPLICABLE",
        "evaluated": False,
        "read_performed": False,
        "required_packages": [],
        "installed_packages": [],
        "missing_packages": [],
        "required_count": 0,
        "installed_count": 0,
        "missing_count": 0,
        "reason": (
            "Package satisfaction is not applicable "
            "to this feature profile."
        ),
    }

    if feature_profile not in APPLICABLE_FEATURES:
        return result

    plan = build_plan(
        feature_profile,
        platform_data=platform_data,
    )

    packages = list(plan.get("packages") or [])

    result["required_packages"] = packages
    result["required_count"] = len(packages)

    if (
        plan.get("platform_profile") != "debian-13"
        or plan.get("package_manager") != "apt"
        or plan.get("package_profile_available") is not True
        or not packages
    ):
        result["satisfaction_status"] = "UNKNOWN"
        result["reason"] = (
            "No supported Debian 13 APT package profile "
            "is available for satisfaction evaluation."
        )
        return result

    result["evaluated"] = True
    result["read_performed"] = True

    try:
        installed_system = parse_installed_packages(
            status_path
        )
    except (OSError, RuntimeError):
        result["satisfaction_status"] = "UNKNOWN"
        result["reason"] = (
            "Installed package state could not be "
            "verified read-only."
        )
        return result

    installed = [
        package
        for package in packages
        if package in installed_system
    ]

    missing = [
        package
        for package in packages
        if package not in installed_system
    ]

    result["installed_packages"] = installed
    result["missing_packages"] = missing
    result["installed_count"] = len(installed)
    result["missing_count"] = len(missing)

    if not missing:
        result["satisfaction_status"] = "SATISFIED"
        result["reason"] = (
            "All required packages are already installed."
        )
    elif installed:
        result["satisfaction_status"] = "PARTIAL"
        result["reason"] = (
            "Only part of the required package profile "
            "is already installed."
        )
    else:
        result["satisfaction_status"] = "MISSING"
        result["reason"] = (
            "None of the required packages are installed."
        )

    return result
