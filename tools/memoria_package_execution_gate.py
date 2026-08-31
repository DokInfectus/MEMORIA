#!/usr/bin/env python3
from __future__ import annotations

import argparse
from typing import Any, Callable

from memoria_package_approval_handoff import (
    request_approval,
    verify_approval_receipt,
    plan_sha256,
)
from memoria_package_install_plan import build_installation_plan
from memoria_package_profile import FEATURE_LABELS


SCHEMA_VERSION = "memoria-package-execution-gate-v0.1"


PlanBuilder = Callable[[str], dict[str, Any]]


def request_execution_confirmation(
    plan: dict[str, Any],
) -> bool:
    print()
    print("MEMORIA PACKAGE EXECUTION GATE V0.1")
    print("-" * 64)
    print("Approved plan was rebuilt and verified.")
    print(f"Verified Plan SHA-256: {plan_sha256(plan)}")
    print(f"Package Count: {plan['package_count']}")
    print()
    print("IMPORTANT:")
    print("This V0.1 gate still executes NO installation command.")
    print("No system change is allowed.")

    answer = input(
        "Verifizierten Plan fuer den spaeteren Executor freigeben? "
        "/ Authorize verified plan for the future executor? "
        "[ja/nein]: "
    ).strip().lower()

    return answer in {"ja", "j", "yes", "y"}


def build_execution_authorization(
    receipt: dict[str, Any],
    current_plan: dict[str, Any],
) -> dict[str, Any]:
    if not verify_approval_receipt(receipt, current_plan):
        raise ValueError(
            "approval receipt does not match the current installation plan"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "authorized": True,
        "plan_sha256": plan_sha256(current_plan),
        "feature_profile": current_plan["feature_profile"],
        "platform_profile": current_plan["platform_profile"],
        "package_manager": current_plan["package_manager"],
        "package_count": current_plan["package_count"],
        "authorization_status": "AUTHORIZED FOR FUTURE EXECUTOR",
        "system_change_allowed": False,
        "installation_status": "BLOCKED",
    }


def run_execution_gate(
    feature_profile: str,
    *,
    plan_builder: PlanBuilder = build_installation_plan,
) -> tuple[int, dict[str, Any] | None]:
    initial_plan = plan_builder(feature_profile)

    if initial_plan.get("installation_status") == "NOT REQUIRED":
        print("PACKAGE EXECUTION GATE: NOT REQUIRED")
        print("No additional optional packages are required.")
        print("No system change allowed.")
        return 0, None

    approval_status, receipt = request_approval(initial_plan)

    if approval_status != 0 or receipt is None:
        print()
        print("PACKAGE EXECUTION GATE: BLOCKED")
        print("No execution authorization created.")
        print("No system change allowed.")
        return approval_status, None

    current_plan = plan_builder(feature_profile)

    if not verify_approval_receipt(receipt, current_plan):
        print()
        print("PACKAGE EXECUTION GATE: BLOCKED")
        print("PLAN CHANGED AFTER APPROVAL")
        print("Approval receipt does not match current plan.")
        print("No execution authorization created.")
        print("No system change allowed.")
        return 4, None

    print()
    print("APPROVAL RECEIPT VERIFIED")
    print(f"Current Plan SHA-256: {plan_sha256(current_plan)}")

    if not request_execution_confirmation(current_plan):
        print()
        print("FINAL EXECUTION AUTHORIZATION DECLINED")
        print("No execution authorization created.")
        print("No system change allowed.")
        return 2, None

    authorization = build_execution_authorization(
        receipt,
        current_plan,
    )

    print()
    print("FINAL EXECUTION AUTHORIZATION CREATED IN MEMORY")
    print(
        "Authorization Status: "
        f"{authorization['authorization_status']}"
    )
    print("NO AUTHORIZATION FILE WRITTEN")
    print("NO INSTALLATION EXECUTED")
    print("Installation remains BLOCKED.")

    return 0, authorization


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify one approved MEMORIA package plan again before "
            "a future package executor may be considered"
        )
    )

    parser.add_argument(
        "--feature",
        required=True,
        choices=tuple(FEATURE_LABELS),
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    status, _authorization = run_execution_gate(
        args.feature,
    )

    return status


if __name__ == "__main__":
    raise SystemExit(main())
