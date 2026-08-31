#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
from typing import Any

from memoria_package_profile import (
    FEATURE_LABELS,
    build_plan,
)
from memoria_platform_detector import detect_platform


SCHEMA_VERSION = "memoria-package-install-plan-v0.1"


def build_installation_plan(
    feature_profile: str,
    platform_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if platform_data is None:
        platform_data = detect_platform()

    package_plan = build_plan(
        feature_profile,
        platform_data=platform_data,
    )

    platform_profile = package_plan.get("platform_profile")
    package_manager = package_plan.get("package_manager")
    packages = list(package_plan.get("packages") or [])

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "feature_profile": package_plan["feature_profile"],
        "feature_label": package_plan["feature_label"],
        "platform_profile": platform_profile,
        "platform_support": package_plan["platform_support"],
        "package_manager": package_manager,
        "package_profile_available": bool(
            package_plan["package_profile_available"]
        ),
        "packages": packages,
        "package_count": len(packages),
        "execution_mode": "DRY RUN ONLY",
        "system_change_allowed": False,
        "approval_handoff": "AVAILABLE AS SEPARATE STAGE",
        "installation_status": "BLOCKED",
        "command_argv": [],
        "command_preview": None,
        "reason": None,
    }

    if not result["package_profile_available"]:
        result["reason"] = (
            "No confirmed package profile is available "
            "for this platform."
        )
        return result

    if platform_profile == "debian-13":
        if package_manager != "apt":
            result["reason"] = (
                "Debian 13 profile requires the expected "
                "APT package-manager path."
            )
            return result

        if not packages:
            result["installation_status"] = "NOT REQUIRED"
            result["reason"] = (
                "Selected feature profile requires no "
                "additional optional packages."
            )
            return result

        argv = [
            "apt-get",
            "install",
            "--yes",
            "--no-install-recommends",
            *packages,
        ]

        result["command_argv"] = argv
        result["command_preview"] = shlex.join(argv)
        result["reason"] = (
            "Dry-run command preview generated. "
            "Execution remains blocked."
        )
        return result

    result["reason"] = (
        "No installation command builder exists "
        "for this platform profile."
    )
    return result


def print_plan(plan: dict[str, Any]) -> None:
    print("MEMORIA PACKAGE INSTALLATION PLAN V0.1")
    print("-" * 64)

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
        "System Change Allowed: "
        + ("yes" if plan["system_change_allowed"] else "no")
    )
    print(f"Approval Handoff: {plan['approval_handoff']}")
    print(f"Installation Status: {plan['installation_status']}")

    if plan["command_preview"]:
        print()
        print("Command Preview:")
        print(plan["command_preview"])

    print()
    print(f"Reason: {plan['reason']}")
    print()
    print("No command was executed.")
    print("No package was installed or changed.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only MEMORIA package installation-plan preview"
        )
    )

    parser.add_argument(
        "--feature",
        required=True,
        choices=tuple(FEATURE_LABELS),
        help="feature profile to plan",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON",
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    plan = build_installation_plan(args.feature)

    if args.json:
        print(
            json.dumps(
                plan,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    else:
        print_plan(plan)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
