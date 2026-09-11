#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from memoria_platform_detector import detect_platform


SCHEMA_VERSION = "memoria-package-profile-v0.1"


INTERNAL_FEATURE_LABELS = {
    "minimal": "Minimal",
    "matrix-ui": "Matrix UI",
    "local-ocr": "Local OCR",
    "matrix-ui+ocr": "Matrix UI + Local OCR",
}


FEATURE_LABELS = {
    feature: INTERNAL_FEATURE_LABELS[feature]
    for feature in (
        "minimal",
        "matrix-ui",
        "local-ocr",
        "matrix-ui+ocr",
    )
}


DEBIAN_13_BASE_PACKAGES = [
    "gpgv",
]


DEBIAN_13_PACKAGES = {
    "minimal": [
        *DEBIAN_13_BASE_PACKAGES,
    ],
    "matrix-ui": [
        *DEBIAN_13_BASE_PACKAGES,
        "python3-tk",
        "tigervnc-standalone-server",
        "tigervnc-tools",
        "novnc",
        "websockify",
        "procps",
        "iproute2",
    ],
    "local-ocr": [
        *DEBIAN_13_BASE_PACKAGES,
        "python3-pil",
        "tesseract-ocr",
        "tesseract-ocr-deu",
        "tesseract-ocr-eng",
    ],
}


def merged_packages(
    *groups: list[str],
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for group in groups:
        for package in group:
            if package in seen:
                continue

            seen.add(package)
            result.append(package)

    return result


DEBIAN_13_PACKAGES["matrix-ui+ocr"] = merged_packages(
    DEBIAN_13_PACKAGES["matrix-ui"],
    DEBIAN_13_PACKAGES["local-ocr"],
)


PACKAGE_PROFILES = {
    "debian-13": DEBIAN_13_PACKAGES,
}


def build_plan(
    feature_profile: str,
    platform_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if feature_profile not in INTERNAL_FEATURE_LABELS:
        raise ValueError(
            f"unsupported feature profile: {feature_profile}"
        )

    if platform_data is None:
        platform_data = detect_platform()

    platform_profile = platform_data.get("profile")

    package_profile_available = (
        platform_profile in PACKAGE_PROFILES
    )

    packages: list[str] = []

    if package_profile_available:
        packages = list(
            PACKAGE_PROFILES[platform_profile][feature_profile]
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "feature_profile": feature_profile,
        "feature_label": INTERNAL_FEATURE_LABELS[feature_profile],
        "platform_profile": platform_profile,
        "platform_support": platform_data.get(
            "support",
            "UNKNOWN / UNSUPPORTED",
        ),
        "package_manager": platform_data.get("package_manager"),
        "package_profile_available": package_profile_available,
        "packages": packages,
        "package_count": len(packages),
        "execution_mode": "PREVIEW ONLY",
        "automatic_package_installation": "BLOCKED",
        "explicit_user_confirmation_required": True,
    }


def print_plan(plan: dict[str, Any]) -> None:
    print("MEMORIA PACKAGE PROFILE V0.1")
    print("-" * 60)
    print(
        "Feature Profile: "
        f"{plan['feature_label']} "
        f"({plan['feature_profile']})"
    )
    print(
        "Platform Profile: "
        f"{plan['platform_profile'] or 'none'}"
    )
    print(
        "Platform Support: "
        f"{plan['platform_support']}"
    )
    print(
        "Package Manager: "
        f"{plan['package_manager'] or 'not detected'}"
    )
    print(
        "Package Profile: "
        + (
            "AVAILABLE"
            if plan["package_profile_available"]
            else "NOT AVAILABLE"
        )
    )
    print()

    print("Packages:")

    if plan["packages"]:
        for package in plan["packages"]:
            print(f"- {package}")
    else:
        print("- none")

    print()
    print(f"Package Count: {plan['package_count']}")
    print(f"Execution Mode: {plan['execution_mode']}")
    print(
        "Automatic package installation: "
        f"{plan['automatic_package_installation']}"
    )
    print(
        "Explicit user confirmation required: "
        + (
            "yes"
            if plan["explicit_user_confirmation_required"]
            else "no"
        )
    )
    print()
    print("Preview completed.")
    print("No package was installed or changed.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only MEMORIA package profile preview"
        )
    )

    selection = parser.add_mutually_exclusive_group(
        required=True
    )

    selection.add_argument(
        "--feature",
        choices=tuple(FEATURE_LABELS),
        help="show one feature profile",
    )

    selection.add_argument(
        "--all",
        action="store_true",
        help="show all feature profiles",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON",
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    features = (
        list(FEATURE_LABELS)
        if args.all
        else [args.feature]
    )

    platform_data = detect_platform()

    plans = [
        build_plan(
            feature,
            platform_data=platform_data,
        )
        for feature in features
    ]

    if args.json:
        output: Any = plans if args.all else plans[0]

        print(
            json.dumps(
                output,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    for index, plan in enumerate(plans):
        if index:
            print()
            print("=" * 60)
            print()

        print_plan(plan)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
