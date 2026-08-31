#!/usr/bin/env python3
from __future__ import annotations

import secrets
from copy import deepcopy
from typing import Any, Callable

from memoria_package_approval_handoff import plan_sha256
from memoria_package_executor import command_shape_is_safe
from memoria_package_transaction_approval import (
    verify_transaction_approval_receipt,
)


SCHEMA_VERSION = (
    "memoria-package-system-change-authorization-v0.1"
)

FLOW_SCHEMA = "memoria-package-execution-flow-v0.1"

TRANSACTION_PREVIEW_SCHEMA = (
    "memoria-package-transaction-preview-v0.1"
)

EXECUTOR_SCHEMA = (
    "memoria-package-executor-dry-run-v0.1"
)

TokenFactory = Callable[[], str]


def _default_token_factory() -> str:
    return secrets.token_urlsafe(24)


def _plan_is_eligible(
    plan: dict[str, Any],
) -> bool:
    return bool(
        plan.get("platform_profile") == "debian-13"
        and plan.get("platform_support")
        == "TESTED / OFFICIALLY SUPPORTED"
        and plan.get("package_manager") == "apt"
        and plan.get("package_profile_available") is True
        and plan.get("execution_mode") == "DRY RUN ONLY"
        and plan.get("system_change_allowed") is False
        and plan.get("installation_status") == "BLOCKED"
        and plan.get("package_count", 0) > 0
        and command_shape_is_safe(plan)
    )


def _flow_is_eligible(
    flow_result: dict[str, Any],
    current_plan: dict[str, Any],
) -> bool:
    if flow_result.get("schema_version") != FLOW_SCHEMA:
        return False

    if flow_result.get("flow_status") != "DRY RUN VERIFIED":
        return False

    if flow_result.get("system_change_allowed") is not False:
        return False

    if flow_result.get("execution_performed") is not False:
        return False

    executor = flow_result.get("executor_result")

    if not isinstance(executor, dict):
        return False

    if executor.get("schema_version") != EXECUTOR_SCHEMA:
        return False

    if executor.get("verified") is not True:
        return False

    if executor.get("executor_status") != "DRY RUN VERIFIED":
        return False

    if executor.get("system_change_allowed") is not False:
        return False

    if executor.get("execution_performed") is not False:
        return False

    if list(executor.get("held_package_locks") or []):
        return False

    expected_hash = plan_sha256(current_plan)

    if executor.get("plan_sha256") != expected_hash:
        return False

    return _plan_is_eligible(current_plan)


def _is_sha256(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(
            char in "0123456789abcdef"
            for char in value
        )
    )


def _transaction_preview_is_eligible(
    transaction_preview: dict[str, Any],
    current_plan: dict[str, Any],
) -> bool:
    if not isinstance(transaction_preview, dict):
        return False

    if transaction_preview.get(
        "schema_version"
    ) != TRANSACTION_PREVIEW_SCHEMA:
        return False

    if transaction_preview.get(
        "preview_status"
    ) != "TRANSACTION PREVIEW VERIFIED":
        return False

    if transaction_preview.get("approvable") is not True:
        return False

    if transaction_preview.get(
        "system_change_allowed"
    ) is not False:
        return False

    if transaction_preview.get(
        "execution_performed"
    ) is not False:
        return False

    if transaction_preview.get(
        "simulation_performed"
    ) is not True:
        return False

    if list(
        transaction_preview.get("removal_lines") or []
    ):
        return False

    if transaction_preview.get(
        "plan_sha256"
    ) != plan_sha256(current_plan):
        return False

    return _is_sha256(
        transaction_preview.get("transaction_sha256")
    )


class OneShotSystemChangeAuthorizationStore:
    """
    Process-local one-shot authorization registry.

    No authorization is written to disk.
    A copied token can still be consumed only once because
    consumption state lives in this process-local registry.
    """

    def __init__(
        self,
        *,
        token_factory: TokenFactory = _default_token_factory,
    ) -> None:
        self._token_factory = token_factory
        self._records: dict[str, dict[str, Any]] = {}

    def issue(
        self,
        flow_result: dict[str, Any],
        current_plan: dict[str, Any],
        transaction_preview: dict[str, Any],
        transaction_approval_receipt: dict[str, Any],
    ) -> dict[str, Any]:
        if not _flow_is_eligible(
            flow_result,
            current_plan,
        ):
            raise ValueError(
                "dry-run flow is not eligible for "
                "system-change authorization"
            )

        if not _transaction_preview_is_eligible(
            transaction_preview,
            current_plan,
        ):
            raise ValueError(
                "transaction preview is not eligible for "
                "system-change authorization"
            )

        if (
            not isinstance(
                transaction_approval_receipt,
                dict,
            )
            or not verify_transaction_approval_receipt(
                transaction_approval_receipt,
                current_plan,
                transaction_preview,
            )
        ):
            raise ValueError(
                "exact transaction approval receipt "
                "is required for system-change authorization"
            )

        token_id = self._token_factory()

        if not isinstance(token_id, str) or not token_id:
            raise ValueError("token factory returned invalid token")

        if token_id in self._records:
            raise ValueError("duplicate one-shot token")

        record = {
            "schema_version": SCHEMA_VERSION,
            "token_id": token_id,
            "authorized_for_system_change": True,
            "authorization_status": (
                "ONE-SHOT SYSTEM CHANGE AUTHORIZATION"
            ),
            "one_shot": True,
            "consumed": False,
            "revoked": False,
            "revocation_reason": None,
            "plan_sha256": plan_sha256(current_plan),
            "transaction_sha256": transaction_preview[
                "transaction_sha256"
            ],
            "transaction_approval_verified": True,
            "transaction_approval_status": (
                "EXACT TRANSACTION APPROVED"
            ),
            "feature_profile": current_plan["feature_profile"],
            "platform_profile": current_plan["platform_profile"],
            "package_manager": current_plan["package_manager"],
            "package_count": current_plan["package_count"],
            "persistence": "MEMORY ONLY",
            "execution_performed": False,
        }

        self._records[token_id] = deepcopy(record)

        return deepcopy(record)

    def verify_and_consume(
        self,
        authorization: dict[str, Any],
        current_plan: dict[str, Any],
        transaction_preview: dict[str, Any],
    ) -> tuple[bool, dict[str, Any]]:
        blocked = {
            "schema_version": SCHEMA_VERSION,
            "authorized_for_system_change": False,
            "authorization_status": "BLOCKED",
            "one_shot": True,
            "consumed": False,
            "revoked": False,
            "revocation_reason": None,
            "plan_sha256": plan_sha256(current_plan),
            "transaction_sha256": None,
            "execution_performed": False,
            "reason": None,
        }

        if authorization.get("schema_version") != SCHEMA_VERSION:
            blocked["reason"] = "Authorization schema mismatch."
            return False, blocked

        token_id = authorization.get("token_id")

        if not isinstance(token_id, str) or not token_id:
            blocked["reason"] = "Missing one-shot token."
            return False, blocked

        record = self._records.get(token_id)

        if record is None:
            blocked["reason"] = (
                "Unknown one-shot authorization."
            )
            return False, blocked

        if record.get("revoked") is True:
            blocked["authorization_status"] = (
                "REVOKED - TRANSACTION DRIFT"
            )
            blocked["revoked"] = True
            blocked["revocation_reason"] = (
                record.get("revocation_reason")
            )
            blocked["transaction_sha256"] = (
                transaction_preview.get("transaction_sha256")
            )
            blocked["reason"] = (
                "One-shot authorization was permanently "
                "revoked after transaction drift."
            )
            return False, blocked

        if record.get("consumed") is True:
            blocked["consumed"] = True
            blocked["reason"] = (
                "One-shot authorization already consumed."
            )
            return False, blocked

        if authorization != record:
            blocked["reason"] = (
                "Presented authorization was modified."
            )
            return False, blocked

        if record.get(
            "authorized_for_system_change"
        ) is not True:
            blocked["reason"] = (
                "System-change authorization is not active."
            )
            return False, blocked

        if record.get("one_shot") is not True:
            blocked["reason"] = (
                "Authorization is not marked one-shot."
            )
            return False, blocked

        if record.get("persistence") != "MEMORY ONLY":
            blocked["reason"] = (
                "Unexpected authorization persistence mode."
            )
            return False, blocked

        if record.get("execution_performed") is not False:
            blocked["reason"] = (
                "Authorization has unexpected execution state."
            )
            return False, blocked

        if record.get(
            "transaction_approval_verified"
        ) is not True:
            blocked["reason"] = (
                "Exact transaction approval is not verified."
            )
            return False, blocked

        if record.get(
            "transaction_approval_status"
        ) != "EXACT TRANSACTION APPROVED":
            blocked["reason"] = (
                "Unexpected transaction approval status."
            )
            return False, blocked

        if not _transaction_preview_is_eligible(
            transaction_preview,
            current_plan,
        ):
            blocked["reason"] = (
                "Current transaction preview is not eligible."
            )
            return False, blocked

        current_transaction_sha = transaction_preview[
            "transaction_sha256"
        ]
        blocked["transaction_sha256"] = (
            current_transaction_sha
        )

        if not _plan_is_eligible(current_plan):
            blocked["reason"] = (
                "Current plan is no longer eligible."
            )
            return False, blocked

        expected_hash = plan_sha256(current_plan)

        if record.get("plan_sha256") != expected_hash:
            blocked["reason"] = (
                "Current plan no longer matches authorization."
            )
            return False, blocked

        if record.get(
            "transaction_sha256"
        ) != current_transaction_sha:
            record["revoked"] = True
            record["revocation_reason"] = "TRANSACTION DRIFT"
            record["authorized_for_system_change"] = False
            record["authorization_status"] = (
                "REVOKED - TRANSACTION DRIFT"
            )

            blocked["authorization_status"] = (
                "REVOKED - TRANSACTION DRIFT"
            )
            blocked["revoked"] = True
            blocked["revocation_reason"] = (
                "TRANSACTION DRIFT"
            )
            blocked["reason"] = (
                "Current transaction no longer matches "
                "authorization. One-shot authorization "
                "permanently revoked."
            )
            return False, blocked

        if (
            record.get("feature_profile")
            != current_plan.get("feature_profile")
        ):
            blocked["reason"] = "Feature profile mismatch."
            return False, blocked

        if (
            record.get("platform_profile")
            != current_plan.get("platform_profile")
        ):
            blocked["reason"] = "Platform profile mismatch."
            return False, blocked

        if (
            record.get("package_manager")
            != current_plan.get("package_manager")
        ):
            blocked["reason"] = "Package manager mismatch."
            return False, blocked

        if (
            record.get("package_count")
            != current_plan.get("package_count")
        ):
            blocked["reason"] = "Package count mismatch."
            return False, blocked

        # Consume BEFORE handing control to a future executor.
        # Even a failed future execution attempt must not make
        # this authorization reusable.
        record["consumed"] = True

        consumed = {
            "schema_version": SCHEMA_VERSION,
            "authorized_for_system_change": True,
            "authorization_status": (
                "CONSUMED FOR ONE EXECUTION ATTEMPT"
            ),
            "one_shot": True,
            "consumed": True,
            "revoked": False,
            "revocation_reason": None,
            "plan_sha256": expected_hash,
            "transaction_sha256": record[
                "transaction_sha256"
            ],
            "transaction_approval_verified": True,
            "transaction_approval_status": (
                "EXACT TRANSACTION APPROVED"
            ),
            "feature_profile": record["feature_profile"],
            "platform_profile": record["platform_profile"],
            "package_manager": record["package_manager"],
            "package_count": record["package_count"],
            "persistence": "MEMORY ONLY",
            "execution_performed": False,
            "reason": (
                "One-shot authorization consumed. "
                "No package execution exists in V0.1."
            ),
        }

        return True, consumed
