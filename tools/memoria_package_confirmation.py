#!/usr/bin/env python3
from __future__ import annotations

import argparse
from typing import Any

from memoria_package_profile import (
    FEATURE_LABELS,
    build_plan,
)
from memoria_platform_detector import detect_platform


YES_VALUES = {
    "ja",
    "j",
    "yes",
    "y",
}

NO_VALUES = {
    "nein",
    "n",
    "no",
    "",
}


def normalize_confirmation(value: str) -> bool | None:
    normalized = str(value or "").strip().lower()

    if normalized in YES_VALUES:
        return True

    if normalized in NO_VALUES:
        return False

    return None


def plan_is_eligible(plan: dict[str, Any]) -> bool:
    return bool(plan.get("package_profile_available"))


def print_plan(plan: dict[str, Any]) -> None:
    print("MEMORIA PACKAGE CONFIRMATION V0.1")
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
    print()

    print("Geplante Pakete / Planned packages:")

    if plan["packages"]:
        for package in plan["packages"]:
            print(f"- {package}")
    else:
        print("- none")

    print()
    print(f"Package Count: {plan['package_count']}")
    print("Execution Mode: CONFIRMATION ONLY")
    print("Package installation: BLOCKED")
    print()


def request_confirmation(plan: dict[str, Any]) -> int:
    if not plan_is_eligible(plan):
        print("ABORT: Kein bestätigtes Paketprofil vorhanden.")
        print("Package installation remains BLOCKED.")
        print("No package was installed or changed.")
        return 3

    print_plan(plan)

    answer = input(
        "Diesen Paketplan freigeben? "
        "/ Approve this package plan? [ja/nein]: "
    )

    approved = normalize_confirmation(answer)

    if approved is None:
        print("ABORT: Bitte ja oder nein eingeben.")
        print("Package installation remains BLOCKED.")
        print("No package was installed or changed.")
        return 2

    if not approved:
        print()
        print("PLAN DECLINED")
        print("Package installation remains BLOCKED.")
        print("No package was installed or changed.")
        return 1

    print()
    print("PLAN APPROVED")
    print("NO INSTALLATION EXECUTED")
    print("Package installation remains BLOCKED.")
    print(
        "A later installer stage must separately "
        "verify this approval before any system change."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "MEMORIA package-plan confirmation gate "
            "without installation"
        )
    )

    parser.add_argument(
        "--feature",
        required=True,
        choices=tuple(FEATURE_LABELS),
        help="feature profile to preview and confirm",
    )

    parser.add_argument(
        "--preview",
        action="store_true",
        help="show confirmation plan without asking",
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    platform_data = detect_platform()

    plan = build_plan(
        args.feature,
        platform_data=platform_data,
    )

    if args.preview:
        if not plan_is_eligible(plan):
            print("Package Profile: NOT AVAILABLE")
            print("Package installation: BLOCKED")
            return 3

        print_plan(plan)
        print("PREVIEW ONLY")
        print("No confirmation requested.")
        print("No package was installed or changed.")
        return 0

    return request_confirmation(plan)


if __name__ == "__main__":
    raise SystemExit(main())
