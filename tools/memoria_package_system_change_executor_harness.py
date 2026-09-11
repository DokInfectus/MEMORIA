#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Callable

from memoria_package_approval_handoff import plan_sha256
from memoria_package_executor import (
    verify_local_executor_prerequisites,
)
from memoria_package_install_plan import (
    build_installation_plan,
)
from memoria_package_transaction_preview import (
    build_transaction_preview,
)
from memoria_package_system_change_authorization import (
    OneShotSystemChangeAuthorizationStore,
)


SCHEMA_VERSION = (
    "memoria-package-system-change-executor-harness-v0.1"
)

PlanBuilder = Callable[[str], dict[str, Any]]
TestRunner = Callable[[list[str]], int]


def _build_preview_for_plan(
    feature_profile: str,
    current_plan: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    return build_transaction_preview(
        feature_profile,
        plan_builder=lambda _feature: current_plan,
    )


def _blocked(
    reason: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "harness_status": "BLOCKED",
        "system_change_allowed": False,
        "execution_performed": False,
        "authorization_consumed": False,
        "test_runner_invoked": False,
        "runner_returncode": None,
        "plan_sha256": None,
        "transaction_sha256": None,
        "reason": reason,
        "preflight_result": None,
        "transaction_preview_result": None,
    }


def run_test_execution_attempt(
    feature_profile: str,
    store: OneShotSystemChangeAuthorizationStore,
    authorization: dict[str, Any],
    runner: TestRunner,
    *,
    plan_builder: PlanBuilder = build_installation_plan,
) -> tuple[int, dict[str, Any]]:
    """
    Exercise the final authorization ordering with a marked test runner.

    This harness provides no production process runner.
    """

    result = _blocked(
        "System-change executor harness has not run."
    )

    if getattr(runner, "memoria_test_runner", None) is not True:
        result["reason"] = (
            "Runner is not an approved MEMORIA test runner."
        )
        return 5, result

    current_plan = plan_builder(feature_profile)

    result["plan_sha256"] = plan_sha256(current_plan)

    preflight = verify_local_executor_prerequisites(
        current_plan
    )
    result["preflight_result"] = preflight

    if preflight.get("verified") is not True:
        result["reason"] = (
            "Local executor preflight failed."
        )
        return 5, result

    preview_status, transaction_preview = (
        _build_preview_for_plan(
            feature_profile,
            current_plan,
        )
    )

    result["transaction_preview_result"] = (
        transaction_preview
    )
    result["transaction_sha256"] = (
        transaction_preview.get("transaction_sha256")
    )

    if (
        preview_status != 0
        or transaction_preview.get("approvable") is not True
    ):
        result["reason"] = (
            "Current APT transaction preview is not approvable."
        )
        return 5, result

    allowed, consumed = store.verify_and_consume(
        authorization,
        current_plan,
        transaction_preview,
    )

    result["authorization_consumed"] = (
        consumed.get("consumed") is True
    )

    if allowed is not True:
        result["reason"] = consumed.get(
            "reason",
            "One-shot authorization rejected.",
        )
        return 5, result

    argv = list(current_plan.get("command_argv") or [])

    result["test_runner_invoked"] = True

    try:
        returncode = runner(argv)
    except Exception as exc:
        result["harness_status"] = "TEST RUNNER ERROR"
        result["reason"] = (
            "Marked test runner raised "
            f"{type(exc).__name__}."
        )
        return 11, result

    if not isinstance(returncode, int):
        result["harness_status"] = "TEST RUNNER ERROR"
        result["reason"] = (
            "Marked test runner returned invalid status."
        )
        return 11, result

    result["runner_returncode"] = returncode
    result["harness_status"] = "TEST RUNNER RETURNED"
    result["reason"] = (
        "Marked test runner was invoked exactly once "
        "for this execution attempt."
    )

    if returncode != 0:
        return 10, result

    return 0, result
