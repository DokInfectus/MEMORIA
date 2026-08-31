#!/usr/bin/env python3
from __future__ import annotations

import subprocess
from typing import Any, Callable

from memoria_package_approval_handoff import plan_sha256
from memoria_package_executor import (
    verify_local_executor_prerequisites,
)
from memoria_package_install_plan import (
    build_installation_plan,
)
from memoria_package_system_change_authorization import (
    OneShotSystemChangeAuthorizationStore,
)
from memoria_package_transaction_preview import (
    SAFE_CHILD_ENV,
    build_transaction_preview,
)


SCHEMA_VERSION = (
    "memoria-package-system-change-runner-v0.1"
)

CANONICAL_APT_GET = "/usr/bin/apt-get"

PlanBuilder = Callable[[str], dict[str, Any]]
ProcessRunner = Callable[
    [list[str], dict[str, str]],
    tuple[int, str],
]


def _default_process_runner(
    argv: list[str],
    env: dict[str, str],
) -> tuple[int, str]:
    completed = subprocess.run(
        argv,
        shell=False,
        check=False,
        cwd="/",
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        close_fds=True,
    )

    return completed.returncode, completed.stdout


def _build_preview_for_plan(
    feature_profile: str,
    current_plan: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    return build_transaction_preview(
        feature_profile,
        plan_builder=lambda _feature: current_plan,
    )


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "runner_status": "BLOCKED",
        "system_change_allowed": False,
        "execution_authorized": False,
        "execution_performed": False,
        "authorization_consumed": False,
        "process_runner_invoked": False,
        "runner_returncode": None,
        "plan_sha256": None,
        "transaction_sha256": None,
        "execution_argv": [],
        "process_output": None,
        "initial_preflight_result": None,
        "transaction_preview_result": None,
        "final_preflight_result": None,
        "reason": reason,
    }


def run_system_change_attempt(
    feature_profile: str,
    store: OneShotSystemChangeAuthorizationStore,
    authorization: dict[str, Any],
    *,
    plan_builder: PlanBuilder = build_installation_plan,
    process_runner: ProcessRunner = _default_process_runner,
) -> tuple[int, dict[str, Any]]:
    """
    Perform exactly one authorized package execution attempt.

    This function has no CLI entry point and writes no authorization
    or execution receipt to disk.
    """

    result = _blocked(
        "Production package system-change runner has not run."
    )

    if (
        process_runner is not _default_process_runner
        and getattr(
            process_runner,
            "memoria_test_runner",
            None,
        ) is not True
    ):
        result["reason"] = (
            "Injected process runner is not an approved "
            "MEMORIA test runner."
        )
        return 5, result

    current_plan = plan_builder(feature_profile)
    current_plan_sha = plan_sha256(current_plan)

    result["plan_sha256"] = current_plan_sha

    initial_preflight = verify_local_executor_prerequisites(
        current_plan
    )
    result["initial_preflight_result"] = initial_preflight

    if initial_preflight.get("verified") is not True:
        result["reason"] = (
            "Initial local executor preflight failed."
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

    if consumed.get(
        "transaction_approval_verified"
    ) is not True:
        result["runner_status"] = "BLOCKED AFTER CONSUME"
        result["reason"] = (
            "Consumed authorization does not carry "
            "verified transaction approval."
        )
        return 6, result

    if consumed.get(
        "transaction_approval_status"
    ) != "EXACT TRANSACTION APPROVED":
        result["runner_status"] = "BLOCKED AFTER CONSUME"
        result["reason"] = (
            "Consumed authorization has unexpected "
            "transaction approval status."
        )
        return 6, result

    final_preflight = verify_local_executor_prerequisites(
        current_plan
    )
    result["final_preflight_result"] = final_preflight

    if final_preflight.get("verified") is not True:
        result["runner_status"] = "BLOCKED AFTER CONSUME"
        result["reason"] = (
            "Final local executor preflight failed after "
            "authorization consumption. No process was invoked."
        )
        return 6, result

    apt_path = final_preflight.get("apt_get_path")

    if apt_path != CANONICAL_APT_GET:
        result["runner_status"] = "BLOCKED AFTER CONSUME"
        result["reason"] = (
            "Final preflight did not return canonical apt-get."
        )
        return 6, result

    if plan_sha256(current_plan) != consumed.get(
        "plan_sha256"
    ):
        result["runner_status"] = "BLOCKED AFTER CONSUME"
        result["reason"] = (
            "Plan changed after authorization consumption."
        )
        return 6, result

    if transaction_preview.get(
        "transaction_sha256"
    ) != consumed.get("transaction_sha256"):
        result["runner_status"] = "BLOCKED AFTER CONSUME"
        result["reason"] = (
            "Transaction changed after authorization consumption."
        )
        return 6, result

    planned_argv = list(
        current_plan.get("command_argv") or []
    )

    if (
        len(planned_argv) < 4
        or planned_argv[0] != "apt-get"
    ):
        result["runner_status"] = "BLOCKED AFTER CONSUME"
        result["reason"] = (
            "Approved command argv is no longer valid."
        )
        return 6, result

    execution_argv = [
        apt_path,
        *planned_argv[1:],
    ]

    result["execution_argv"] = execution_argv
    result["execution_authorized"] = True

    # From this exact point onward, conservatively record that
    # a real system-change attempt has crossed the process boundary.
    result["process_runner_invoked"] = True
    result["execution_performed"] = True

    try:
        returncode, output = process_runner(
            execution_argv,
            dict(SAFE_CHILD_ENV),
        )
    except Exception as exc:
        result["runner_status"] = "EXECUTION ERROR"
        result["reason"] = (
            "Package process runner raised "
            f"{type(exc).__name__}. "
            "Authorization remains consumed; "
            "system state must be inspected before any new attempt."
        )
        return 11, result

    if (
        type(returncode) is not int
        or not isinstance(output, str)
    ):
        result["runner_status"] = "EXECUTION ERROR"
        result["reason"] = (
            "Package process runner returned an invalid result. "
            "Authorization remains consumed."
        )
        return 11, result

    result["runner_returncode"] = returncode
    result["process_output"] = output

    if returncode != 0:
        result["runner_status"] = "EXECUTION FAILED"
        result["reason"] = (
            "apt-get returned non-zero status. "
            "No automatic retry is allowed; "
            "authorization remains consumed."
        )
        return 10, result

    result["runner_status"] = "EXECUTION COMPLETED"
    result["reason"] = (
        "The single authorized apt-get execution attempt "
        "returned status 0. Authorization is consumed."
    )

    return 0, result
