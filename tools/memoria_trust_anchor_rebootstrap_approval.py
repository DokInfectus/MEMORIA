#!/usr/bin/env python3
from __future__ import annotations

import secrets
from copy import deepcopy
from typing import Any, Callable

from memoria_trust_anchor_rebootstrap_plan import (
    verify_rebootstrap_plan_identity,
)


SCHEMA_VERSION = (
    "memoria-trust-anchor-rebootstrap-approval-v0.1"
)
PLAN_SCHEMA = (
    "memoria-trust-anchor-rebootstrap-plan-v0.1"
)

APPROVAL_STATUS = (
    "EXACT TRUST ANCHOR REBOOTSTRAP PLAN APPROVED"
)
TRANSITION_AUTHORITY = (
    "EXPLICIT ADMIN REBOOTSTRAP"
)

ApprovalIdFactory = Callable[[], str]


def _default_approval_id_factory() -> str:
    return secrets.token_urlsafe(24)


def _is_sha256(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(
            char in "0123456789abcdef"
            for char in value
        )
    )


def _is_fingerprint(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 40
        and all(
            char in "0123456789ABCDEF"
            for char in value
        )
    )


def rebootstrap_plan_is_approvable(
    plan: dict[str, Any],
) -> bool:
    if not isinstance(plan, dict):
        return False

    return bool(
        plan.get("schema_version") == PLAN_SCHEMA
        and plan.get("plan_status")
        == "READY FOR ADMIN APPROVAL"
        and plan.get("approvable") is True
        and plan.get("system_change_allowed") is False
        and plan.get("execution_performed") is False
        and plan.get("transition_authority")
        == TRANSITION_AUTHORITY
        and plan.get("target_state")
        == "EXPECTED CURRENT ANCHOR"
        and _is_sha256(plan.get("source_sha256"))
        and _is_sha256(plan.get("target_sha256"))
        and _is_sha256(
            plan.get("expected_current_sha256")
        )
        and _is_sha256(
            plan.get("expected_replacement_sha256")
        )
        and plan.get("target_sha256")
        == plan.get("expected_current_sha256")
        and plan.get("source_sha256")
        == plan.get("expected_replacement_sha256")
        and _is_fingerprint(
            plan.get("historical_fingerprint")
        )
        and _is_fingerprint(
            plan.get("current_fingerprint")
        )
        and plan.get("historical_fingerprint")
        != plan.get("current_fingerprint")
        and _is_sha256(plan.get("plan_sha256"))
        and verify_rebootstrap_plan_identity(plan)
    )


def _bound_identity(
    plan: dict[str, Any],
) -> dict[str, Any]:
    fields = (
        "plan_sha256",
        "transition_authority",
        "source_path",
        "source_sha256",
        "target_path",
        "target_state",
        "target_sha256",
        "target_mode",
        "target_uid",
        "target_gid",
        "expected_current_sha256",
        "expected_replacement_sha256",
        "historical_fingerprint",
        "current_fingerprint",
        "required_target_mode",
        "required_target_uid",
        "required_target_gid",
    )

    return {
        field: deepcopy(plan.get(field))
        for field in fields
    }


def build_rebootstrap_approval_receipt(
    plan: dict[str, Any],
    *,
    approval_id: str,
) -> dict[str, Any]:
    if not rebootstrap_plan_is_approvable(plan):
        raise ValueError(
            "rebootstrap plan is not eligible "
            "for explicit admin approval"
        )

    if not isinstance(approval_id, str) or not approval_id:
        raise ValueError("invalid approval identity")

    return {
        "schema_version": SCHEMA_VERSION,
        "approval_id": approval_id,
        "approved": True,
        "approval_status": APPROVAL_STATUS,
        "persistence": "MEMORY ONLY",
        "system_change_allowed": False,
        "execution_performed": False,
        "bound_identity": _bound_identity(plan),
    }


def verify_rebootstrap_approval_receipt(
    receipt: dict[str, Any],
    plan: dict[str, Any],
) -> bool:
    if not rebootstrap_plan_is_approvable(plan):
        return False

    if not isinstance(receipt, dict):
        return False

    if receipt.get("schema_version") != SCHEMA_VERSION:
        return False

    approval_id = receipt.get("approval_id")

    if not isinstance(approval_id, str) or not approval_id:
        return False

    if receipt.get("approved") is not True:
        return False

    if receipt.get("approval_status") != APPROVAL_STATUS:
        return False

    if receipt.get("persistence") != "MEMORY ONLY":
        return False

    if receipt.get("system_change_allowed") is not False:
        return False

    if receipt.get("execution_performed") is not False:
        return False

    return (
        receipt.get("bound_identity")
        == _bound_identity(plan)
    )


class TrustAnchorRebootstrapApprovalStore:
    """
    Process-local registry of explicit admin
    rebootstrap approval events.

    One approval event may be claimed exactly once
    for a future rebootstrap authorization.

    Nothing is persisted to disk.
    """

    def __init__(
        self,
        *,
        approval_id_factory: ApprovalIdFactory = (
            _default_approval_id_factory
        ),
    ) -> None:
        self._approval_id_factory = approval_id_factory
        self._records: dict[str, dict[str, Any]] = {}

    def issue(
        self,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        if not rebootstrap_plan_is_approvable(plan):
            raise ValueError(
                "rebootstrap plan is not eligible "
                "for explicit admin approval"
            )

        approval_id = self._approval_id_factory()

        if not isinstance(approval_id, str) or not approval_id:
            raise ValueError(
                "approval id factory returned "
                "invalid identity"
            )

        if approval_id in self._records:
            raise ValueError(
                "duplicate approval identity"
            )

        receipt = build_rebootstrap_approval_receipt(
            plan,
            approval_id=approval_id,
        )

        self._records[approval_id] = {
            "receipt": deepcopy(receipt),
            "authorization_claimed": False,
        }

        return deepcopy(receipt)

    def verify_unclaimed(
        self,
        receipt: dict[str, Any],
        plan: dict[str, Any],
    ) -> bool:
        if not verify_rebootstrap_approval_receipt(
            receipt,
            plan,
        ):
            return False

        approval_id = receipt.get("approval_id")
        record = self._records.get(approval_id)

        if record is None:
            return False

        if record.get("authorization_claimed") is True:
            return False

        return receipt == record.get("receipt")

    def claim_for_authorization(
        self,
        receipt: dict[str, Any],
        plan: dict[str, Any],
    ) -> bool:
        if not self.verify_unclaimed(
            receipt,
            plan,
        ):
            return False

        record = self._records[
            receipt["approval_id"]
        ]

        record["authorization_claimed"] = True
        return True
