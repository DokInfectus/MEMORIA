#!/usr/bin/env python3
from __future__ import annotations

import argparse
from typing import Any, Callable

from memoria_package_execution_gate import run_execution_gate
from memoria_package_executor import verify_executor_dry_run
from memoria_package_install_plan import build_installation_plan
from memoria_package_profile import FEATURE_LABELS


SCHEMA_VERSION = "memoria-package-execution-flow-v0.1"

PlanBuilder = Callable[[str], dict[str, Any]]


def blocked_result(reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "flow_status": "BLOCKED",
        "system_change_allowed": False,
        "execution_performed": False,
        "reason": reason,
        "executor_result": None,
    }


def run_package_execution_flow(
    feature_profile: str,
    *,
    plan_builder: PlanBuilder = build_installation_plan,
) -> tuple[int, dict[str, Any]]:
    gate_status, authorization = run_execution_gate(
        feature_profile,
        plan_builder=plan_builder,
    )

    if gate_status != 0:
        return gate_status, blocked_result(
            f"Execution Gate returned status {gate_status}."
        )

    if authorization is None:
        current_plan = plan_builder(feature_profile)

        if current_plan.get("installation_status") == "NOT REQUIRED":
            return 0, {
                "schema_version": SCHEMA_VERSION,
                "flow_status": "NOT REQUIRED",
                "system_change_allowed": False,
                "execution_performed": False,
                "reason": (
                    "No additional optional packages are required."
                ),
                "executor_result": None,
            }

        return 5, blocked_result(
            "Execution Gate returned no authorization."
        )

    # Third fresh plan build:
    # authorization must still match immediately before
    # the dry-run executor boundary.
    current_plan = plan_builder(feature_profile)

    executor_result = verify_executor_dry_run(
        authorization,
        current_plan,
    )

    if executor_result.get("verified") is not True:
        result = blocked_result(
            "Dry-run executor verification failed."
        )
        result["executor_result"] = executor_result
        return 5, result

    return 0, {
        "schema_version": SCHEMA_VERSION,
        "flow_status": "DRY RUN VERIFIED",
        "system_change_allowed": False,
        "execution_performed": False,
        "reason": (
            "Execution Gate authorization passed directly "
            "to the dry-run executor in the same process."
        ),
        "executor_result": executor_result,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the MEMORIA package authorization and "
            "executor dry-run chain in one Python process"
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

    status, result = run_package_execution_flow(
        args.feature,
    )

    print()
    print("MEMORIA PACKAGE EXECUTION FLOW V0.1")
    print("-" * 64)
    print(f"Flow Status: {result['flow_status']}")
    print("Authorization Persistence: NONE")
    print("System Change Allowed: no")
    print("Execution Performed: no")
    print(f"Reason: {result['reason']}")
    print("NO AUTHORIZATION FILE WRITTEN")
    print("NO INSTALLATION EXECUTED")

    return status


if __name__ == "__main__":
    raise SystemExit(main())
