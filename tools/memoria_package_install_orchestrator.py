#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Callable

from memoria_package_approval_handoff import plan_sha256
from memoria_package_execution_flow import (
    run_package_execution_flow,
)
from memoria_package_install_plan import (
    build_installation_plan,
)
from memoria_package_system_change_authorization import (
    OneShotSystemChangeAuthorizationStore,
)
from memoria_package_system_change_runner import (
    run_system_change_attempt,
)
from memoria_package_transaction_approval import (
    request_transaction_approval,
)
from memoria_package_transaction_preview import (
    build_transaction_preview,
)


SCHEMA_VERSION = (
    "memoria-package-install-orchestrator-v0.1"
)

PlanBuilder = Callable[[str], dict[str, Any]]
FlowRunner = Callable[..., tuple[int, dict[str, Any]]]
PreviewBuilder = Callable[..., tuple[int, dict[str, Any]]]
ApprovalRequester = Callable[
    [dict[str, Any], dict[str, Any]],
    tuple[int, dict[str, Any] | None],
]
StoreFactory = Callable[
    [],
    OneShotSystemChangeAuthorizationStore,
]


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "orchestrator_status": "BLOCKED",
        "stage": "not-started",
        "plan_sha256": None,
        "transaction_sha256": None,
        "transaction_approval_created": False,
        "authorization_issued": False,
        "execution_performed": False,
        "flow_result": None,
        "transaction_preview_result": None,
        "runner_result": None,
        "reason": reason,
    }


def run_package_installation_orchestrator(
    feature_profile: str,
    *,
    plan_builder: PlanBuilder = build_installation_plan,
    flow_runner: FlowRunner = run_package_execution_flow,
    preview_builder: PreviewBuilder = build_transaction_preview,
    approval_requester: ApprovalRequester = (
        request_transaction_approval
    ),
    store_factory: StoreFactory = (
        OneShotSystemChangeAuthorizationStore
    ),
    process_runner: Any = None,
) -> tuple[int, dict[str, Any]]:
    """
    Coordinate one explicit package-installation transaction.

    The orchestrator owns no subprocess implementation and persists
    no approval, authorization, or execution receipt.
    """

    result = _blocked(
        "Package installation orchestrator has not run."
    )

    result["stage"] = "execution-flow"

    flow_status, flow_result = flow_runner(
        feature_profile,
        plan_builder=plan_builder,
    )

    result["flow_result"] = flow_result

    if flow_status != 0:
        result["reason"] = (
            f"Package execution flow returned status "
            f"{flow_status}."
        )
        return flow_status, result

    if flow_result.get("flow_status") == "NOT REQUIRED":
        result["orchestrator_status"] = "NOT REQUIRED"
        result["stage"] = "complete"
        result["reason"] = (
            "No additional optional packages are required."
        )
        return 0, result

    if flow_result.get("flow_status") != "DRY RUN VERIFIED":
        result["reason"] = (
            "Package execution flow is not DRY RUN VERIFIED."
        )
        return 5, result

    result["stage"] = "transaction-preview"

    current_plan = plan_builder(feature_profile)
    current_plan_sha = plan_sha256(current_plan)
    result["plan_sha256"] = current_plan_sha

    if current_plan.get("installation_status") == "NOT REQUIRED":
        result["reason"] = (
            "Plan became NOT REQUIRED after a verified "
            "package execution flow."
        )
        return 5, result

    preview_status, transaction_preview = preview_builder(
        feature_profile,
        plan_builder=lambda _feature: current_plan,
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
            "APT transaction preview is not approvable."
        )
        return preview_status if preview_status != 0 else 5, result

    result["stage"] = "transaction-approval"

    approval_status, approval_receipt = approval_requester(
        current_plan,
        transaction_preview,
    )

    if approval_status != 0 or approval_receipt is None:
        result["reason"] = (
            "Exact transaction approval was not granted."
        )
        return (
            approval_status
            if approval_status != 0
            else 5
        ), result

    result["transaction_approval_created"] = True

    result["stage"] = "one-shot-authorization"

    store = store_factory()

    try:
        authorization = store.issue(
            flow_result,
            current_plan,
            transaction_preview,
            approval_receipt,
        )
    except ValueError as exc:
        result["reason"] = (
            "One-shot authorization could not be issued: "
            f"{exc}"
        )
        return 5, result

    result["authorization_issued"] = True
    result["stage"] = "production-runner"

    if process_runner is None:
        runner_status, runner_result = (
            run_system_change_attempt(
                feature_profile,
                store,
                authorization,
                plan_builder=plan_builder,
            )
        )
    else:
        runner_status, runner_result = (
            run_system_change_attempt(
                feature_profile,
                store,
                authorization,
                plan_builder=plan_builder,
                process_runner=process_runner,
            )
        )

    result["runner_result"] = runner_result
    result["execution_performed"] = (
        runner_result.get("execution_performed") is True
    )

    if runner_status != 0:
        result["orchestrator_status"] = (
            runner_result.get("runner_status")
            or "BLOCKED"
        )
        result["reason"] = runner_result.get(
            "reason",
            "Production runner did not complete.",
        )
        return runner_status, result

    result["orchestrator_status"] = "EXECUTION COMPLETED"
    result["stage"] = "complete"
    result["reason"] = (
        "Exactly one approved package execution attempt "
        "completed successfully."
    )

    return 0, result
