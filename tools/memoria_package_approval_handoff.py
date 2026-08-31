#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from typing import Any

from memoria_package_install_plan import (
    build_installation_plan,
)
from memoria_package_profile import FEATURE_LABELS


SCHEMA_VERSION = "memoria-package-approval-handoff-v0.1"


def canonical_plan_payload(
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Return exactly the fields bound by user approval."""

    return {
        "feature_profile": plan.get("feature_profile"),
        "platform_profile": plan.get("platform_profile"),
        "platform_support": plan.get("platform_support"),
        "package_manager": plan.get("package_manager"),
        "packages": list(plan.get("packages") or []),
        "package_count": int(plan.get("package_count") or 0),
        "command_argv": list(plan.get("command_argv") or []),
        "command_preview": plan.get("command_preview"),
        "execution_mode": plan.get("execution_mode"),
        "installation_status": plan.get("installation_status"),
    }


def plan_sha256(
    plan: dict[str, Any],
) -> str:
    payload = canonical_plan_payload(plan)

    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(canonical).hexdigest()


def plan_is_approvable(
    plan: dict[str, Any],
) -> bool:
    return bool(
        plan.get("package_profile_available")
        and plan.get("installation_status") == "BLOCKED"
        and plan.get("command_argv")
        and plan.get("package_count", 0) > 0
        and plan.get("system_change_allowed") is False
    )


def build_approval_receipt(
    plan: dict[str, Any],
) -> dict[str, Any]:
    if not plan_is_approvable(plan):
        raise ValueError(
            "installation plan is not eligible for approval handoff"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "approved": True,
        "plan_sha256": plan_sha256(plan),
        "feature_profile": plan["feature_profile"],
        "platform_profile": plan["platform_profile"],
        "package_manager": plan["package_manager"],
        "package_count": plan["package_count"],
        "handoff_status": "APPROVED FOR NEXT STAGE",
        "system_change_allowed": False,
        "installation_status": "BLOCKED",
    }


def verify_approval_receipt(
    receipt: dict[str, Any],
    plan: dict[str, Any],
) -> bool:
    if receipt.get("schema_version") != SCHEMA_VERSION:
        return False

    if receipt.get("approved") is not True:
        return False

    if receipt.get("system_change_allowed") is not False:
        return False

    if receipt.get("installation_status") != "BLOCKED":
        return False

    if receipt.get("feature_profile") != plan.get("feature_profile"):
        return False

    if receipt.get("platform_profile") != plan.get("platform_profile"):
        return False

    if receipt.get("package_manager") != plan.get("package_manager"):
        return False

    if receipt.get("package_count") != plan.get("package_count"):
        return False

    expected_hash = plan_sha256(plan)

    return receipt.get("plan_sha256") == expected_hash


def print_plan_for_approval(
    plan: dict[str, Any],
) -> None:
    print("MEMORIA PACKAGE APPROVAL HANDOFF V0.1")
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
    print(f"Plan SHA-256: {plan_sha256(plan)}")
    print("System Change Allowed: no")
    print("Installation Status: BLOCKED")


def request_approval(
    plan: dict[str, Any],
) -> tuple[int, dict[str, Any] | None]:
    if not plan_is_approvable(plan):
        print("APPROVAL HANDOFF BLOCKED")
        print("Installation plan is not eligible.")
        print("No system change allowed.")
        return 3, None

    print_plan_for_approval(plan)

    answer = input(
        "Exakt diesen Plan freigeben? "
        "/ Approve exactly this plan? [ja/nein]: "
    ).strip().lower()

    if answer not in {"ja", "j", "yes", "y"}:
        print()
        print("PLAN DECLINED")
        print("Approval receipt: NOT CREATED")
        print("Installation remains BLOCKED.")
        return 1, None

    receipt = build_approval_receipt(plan)

    print()
    print("PLAN APPROVED")
    print(f"Approved Plan SHA-256: {receipt['plan_sha256']}")
    print("Approval Handoff: CREATED IN MEMORY")
    print("NO RECEIPT FILE WRITTEN")
    print("NO INSTALLATION EXECUTED")
    print("Installation remains BLOCKED.")

    return 0, receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Bind explicit user approval to one exact "
            "MEMORIA package installation plan"
        )
    )

    parser.add_argument(
        "--feature",
        required=True,
        choices=tuple(FEATURE_LABELS),
    )

    parser.add_argument(
        "--preview",
        action="store_true",
        help="show plan fingerprint without approval",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="print approval receipt JSON after approval",
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    plan = build_installation_plan(args.feature)

    if args.preview:
        print_plan_for_approval(plan)
        print()
        print("PREVIEW ONLY")
        print("Approval receipt: NOT CREATED")
        print("No system change allowed.")
        return 0

    status, receipt = request_approval(plan)

    if status == 0 and args.json and receipt is not None:
        print()
        print(
            json.dumps(
                receipt,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    return status


if __name__ == "__main__":
    raise SystemExit(main())
