#!/usr/bin/env python3
from __future__ import annotations

import secrets
from copy import deepcopy
from typing import Any, Callable

from memoria_trust_anchor_plan import (
    verify_trust_anchor_plan_identity,
)


SCHEMA_VERSION = "memoria-trust-anchor-approval-v0.1"
PLAN_SCHEMA = "memoria-trust-anchor-plan-v0.1"

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


def trust_anchor_plan_is_approvable(
    plan: dict[str, Any],
) -> bool:
    if not isinstance(plan, dict):
        return False

    return bool(
        plan.get("schema_version") == PLAN_SCHEMA
        and plan.get("plan_status") == "READY FOR APPROVAL"
        and plan.get("approvable") is True
        and plan.get("system_change_allowed") is False
        and plan.get("execution_performed") is False
        and plan.get("target_state") == "ABSENT"
        and _is_sha256(plan.get("source_sha256"))
        and isinstance(
            plan.get("source_fingerprint"),
            str,
        )
        and bool(plan.get("source_fingerprint"))
        and _is_sha256(plan.get("plan_sha256"))
        and verify_trust_anchor_plan_identity(plan)
    )


def _bound_identity(
    plan: dict[str, Any],
) -> dict[str, Any]:
    fields = (
        "plan_sha256",
        "source_path",
        "source_sha256",
        "source_fingerprint",
        "signature_path",
        "signature_sha256",
        "sums_path",
        "sums_sha256",
        "target_path",
        "target_state",
        "target_sha256",
        "target_mode",
        "target_uid",
        "target_gid",
        "required_target_mode",
        "required_target_uid",
        "required_target_gid",
    )

    return {
        field: deepcopy(plan.get(field))
        for field in fields
    }


def build_trust_anchor_approval_receipt(
    plan: dict[str, Any],
    *,
    approval_id: str,
) -> dict[str, Any]:
    if not trust_anchor_plan_is_approvable(plan):
        raise ValueError(
            "trust-anchor plan is not eligible "
            "for explicit approval"
        )

    if not isinstance(approval_id, str) or not approval_id:
        raise ValueError("invalid approval identity")

    return {
        "schema_version": SCHEMA_VERSION,
        "approval_id": approval_id,
        "approved": True,
        "approval_status": (
            "EXACT TRUST ANCHOR PLAN APPROVED"
        ),
        "persistence": "MEMORY ONLY",
        "system_change_allowed": False,
        "execution_performed": False,
        "bound_identity": _bound_identity(plan),
    }


def verify_trust_anchor_approval_receipt(
    receipt: dict[str, Any],
    plan: dict[str, Any],
) -> bool:
    if not trust_anchor_plan_is_approvable(plan):
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

    if receipt.get("approval_status") != (
        "EXACT TRUST ANCHOR PLAN APPROVED"
    ):
        return False

    if receipt.get("persistence") != "MEMORY ONLY":
        return False

    if receipt.get("system_change_allowed") is not False:
        return False

    if receipt.get("execution_performed") is not False:
        return False

    return receipt.get(
        "bound_identity"
    ) == _bound_identity(plan)


class TrustAnchorApprovalStore:
    """
    Process-local registry of explicit approval events.

    Copies remain the same approval event.
    One approval event may be claimed for at most one
    future authorization issuance.
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
        if not trust_anchor_plan_is_approvable(plan):
            raise ValueError(
                "trust-anchor plan is not eligible "
                "for explicit approval"
            )

        approval_id = self._approval_id_factory()

        if not isinstance(approval_id, str) or not approval_id:
            raise ValueError(
                "approval id factory returned invalid identity"
            )

        if approval_id in self._records:
            raise ValueError("duplicate approval identity")

        receipt = build_trust_anchor_approval_receipt(
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
        if not verify_trust_anchor_approval_receipt(
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

        record = self._records[receipt["approval_id"]]

        # Claim before a future authorization is issued.
        # Copy/paste cannot turn this receipt into a
        # second approval event.
        record["authorization_claimed"] = True

        return True


def print_trust_anchor_plan_for_approval(
    plan: dict[str, Any],
) -> None:
    print("MEMORIA TRUST ANCHOR APPROVAL V0.1")
    print("-" * 64)
    print(f"Source: {plan['source_path']}")
    print(f"Source SHA-256: {plan['source_sha256']}")
    print(
        "Fingerprint: "
        f"{plan['source_fingerprint']}"
    )
    print(f"Target: {plan['target_path']}")
    print(
        "Required target metadata: "
        f"mode={plan['required_target_mode']} "
        f"uid={plan['required_target_uid']} "
        f"gid={plan['required_target_gid']}"
    )
    print(f"Plan SHA-256: {plan['plan_sha256']}")
    print("System Change Allowed: no")
    print("Approval Persistence: MEMORY ONLY")


def request_trust_anchor_approval(
    plan: dict[str, Any],
    approval_store: TrustAnchorApprovalStore,
) -> tuple[int, dict[str, Any] | None]:
    if not trust_anchor_plan_is_approvable(plan):
        print("TRUST ANCHOR APPROVAL BLOCKED")
        print("Plan is not approvable.")
        print("No system change allowed.")
        return 3, None

    print_trust_anchor_plan_for_approval(plan)
    print()

    answer = input(
        "Exakt diesen Trust-Anchor-Plan freigeben? "
        "/ Approve exactly this trust-anchor plan? "
        "[ja/nein]: "
    ).strip().lower()

    if answer not in {"ja", "j", "yes", "y"}:
        print()
        print("TRUST ANCHOR PLAN DECLINED")
        print("Approval receipt: NOT CREATED")
        print("No system change allowed.")
        return 1, None

    receipt = approval_store.issue(plan)

    print()
    print("TRUST ANCHOR PLAN APPROVED")
    print(f"Approved Plan SHA-256: {plan['plan_sha256']}")
    print(f"Approval ID: {receipt['approval_id']}")
    print("Approval Receipt: CREATED IN MEMORY")
    print("NO RECEIPT FILE WRITTEN")
    print("NO TRUST ANCHOR INSTALLED")
    print("System change remains BLOCKED.")

    return 0, receipt
