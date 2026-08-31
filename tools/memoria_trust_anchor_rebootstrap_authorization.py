#!/usr/bin/env python3
from __future__ import annotations

import secrets
from copy import deepcopy
from typing import Any, Callable

from memoria_trust_anchor_rebootstrap_approval import (
    TrustAnchorRebootstrapApprovalStore,
    rebootstrap_plan_is_approvable,
)
from memoria_trust_anchor_rebootstrap_plan import (
    verify_rebootstrap_plan_identity,
)


SCHEMA_VERSION = (
    "memoria-trust-anchor-rebootstrap-authorization-v0.1"
)

AUTHORIZATION_STATUS = (
    "ONE-SHOT TRUST ANCHOR REBOOTSTRAP AUTHORIZATION"
)

TokenFactory = Callable[[], str]


def _default_token_factory() -> str:
    return secrets.token_urlsafe(24)


class TrustAnchorRebootstrapAuthorizationStore:
    """
    Process-local one-shot authorization registry
    for explicit Trust Anchor admin rebootstrap.

    Approval is claimed before token creation.

    A plan drift permanently revokes the token.
    Nothing is persisted to disk.
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
        plan: dict[str, Any],
        approval_receipt: dict[str, Any],
        approval_store: TrustAnchorRebootstrapApprovalStore,
    ) -> dict[str, Any]:
        if not rebootstrap_plan_is_approvable(plan):
            raise ValueError(
                "rebootstrap plan is not eligible "
                "for authorization"
            )

        if not verify_rebootstrap_plan_identity(plan):
            raise ValueError(
                "rebootstrap plan identity is invalid"
            )

        # Claim FIRST.
        #
        # After this point the explicit admin approval
        # event cannot be reused even if token creation
        # or any later step fails.
        if not approval_store.claim_for_authorization(
            approval_receipt,
            plan,
        ):
            raise ValueError(
                "fresh registered rebootstrap "
                "approval is required"
            )

        token_id = self._token_factory()

        if not isinstance(token_id, str) or not token_id:
            raise ValueError(
                "token factory returned invalid token"
            )

        if token_id in self._records:
            raise ValueError(
                "duplicate one-shot token"
            )

        record = {
            "schema_version": SCHEMA_VERSION,
            "token_id": token_id,
            "approval_id": approval_receipt[
                "approval_id"
            ],
            "plan_sha256": plan["plan_sha256"],
            "authorized_for_trust_anchor_rebootstrap": True,
            "authorization_status": AUTHORIZATION_STATUS,
            "one_shot": True,
            "consumed": False,
            "revoked": False,
            "revocation_reason": None,
            "persistence": "MEMORY ONLY",
            "execution_performed": False,
        }

        self._records[token_id] = deepcopy(record)

        return deepcopy(record)

    def _revoke(
        self,
        record: dict[str, Any],
        reason: str,
    ) -> None:
        record["revoked"] = True
        record["revocation_reason"] = reason
        record[
            "authorized_for_trust_anchor_rebootstrap"
        ] = False
        record["authorization_status"] = (
            f"REVOKED - {reason}"
        )

    def verify_and_consume(
        self,
        authorization: dict[str, Any],
        current_plan: dict[str, Any],
    ) -> tuple[bool, dict[str, Any]]:
        current_plan_sha = None

        if isinstance(current_plan, dict):
            current_plan_sha = current_plan.get(
                "plan_sha256"
            )

        blocked = {
            "schema_version": SCHEMA_VERSION,
            "authorized_for_trust_anchor_rebootstrap": False,
            "authorization_status": "BLOCKED",
            "one_shot": True,
            "consumed": False,
            "revoked": False,
            "revocation_reason": None,
            "plan_sha256": current_plan_sha,
            "approval_id": None,
            "execution_performed": False,
            "reason": None,
        }

        if not isinstance(current_plan, dict):
            blocked["reason"] = (
                "Current plan must be a mapping."
            )
            return False, blocked

        if not isinstance(authorization, dict):
            blocked["reason"] = (
                "Authorization must be a mapping."
            )
            return False, blocked

        if authorization.get(
            "schema_version"
        ) != SCHEMA_VERSION:
            blocked["reason"] = (
                "Authorization schema mismatch."
            )
            return False, blocked

        token_id = authorization.get("token_id")

        if not isinstance(token_id, str) or not token_id:
            blocked["reason"] = (
                "Missing one-shot token."
            )
            return False, blocked

        record = self._records.get(token_id)

        if record is None:
            blocked["reason"] = (
                "Unknown one-shot authorization."
            )
            return False, blocked

        blocked["approval_id"] = record.get(
            "approval_id"
        )

        if record.get("revoked") is True:
            blocked["authorization_status"] = (
                record["authorization_status"]
            )
            blocked["revoked"] = True
            blocked["revocation_reason"] = (
                record.get("revocation_reason")
            )
            blocked["reason"] = (
                "One-shot authorization was "
                "permanently revoked."
            )
            return False, blocked

        if record.get("consumed") is True:
            blocked["consumed"] = True
            blocked["reason"] = (
                "One-shot authorization already consumed."
            )
            return False, blocked

        # A modified copy does not consume or revoke
        # the legitimate registered authorization.
        if authorization != record:
            blocked["reason"] = (
                "Presented authorization was modified."
            )
            return False, blocked

        if not verify_rebootstrap_plan_identity(
            current_plan
        ):
            self._revoke(
                record,
                "PLAN IDENTITY DRIFT",
            )

            blocked["authorization_status"] = (
                record["authorization_status"]
            )
            blocked["revoked"] = True
            blocked["revocation_reason"] = (
                record["revocation_reason"]
            )
            blocked["reason"] = (
                "Current plan identity is invalid; "
                "authorization permanently revoked."
            )
            return False, blocked

        if not rebootstrap_plan_is_approvable(
            current_plan
        ):
            self._revoke(
                record,
                "PLAN STATE DRIFT",
            )

            blocked["authorization_status"] = (
                record["authorization_status"]
            )
            blocked["revoked"] = True
            blocked["revocation_reason"] = (
                record["revocation_reason"]
            )
            blocked["reason"] = (
                "Current plan is no longer approvable; "
                "authorization permanently revoked."
            )
            return False, blocked

        if record.get("plan_sha256") != (
            current_plan.get("plan_sha256")
        ):
            self._revoke(
                record,
                "PLAN HASH DRIFT",
            )

            blocked["authorization_status"] = (
                record["authorization_status"]
            )
            blocked["revoked"] = True
            blocked["revocation_reason"] = (
                record["revocation_reason"]
            )
            blocked["reason"] = (
                "Current plan no longer matches "
                "authorization; permanently revoked."
            )
            return False, blocked

        if record.get(
            "authorized_for_trust_anchor_rebootstrap"
        ) is not True:
            blocked["reason"] = (
                "Trust Anchor rebootstrap "
                "authorization is inactive."
            )
            return False, blocked

        if record.get("one_shot") is not True:
            blocked["reason"] = (
                "Authorization is not marked one-shot."
            )
            return False, blocked

        if record.get("persistence") != "MEMORY ONLY":
            blocked["reason"] = (
                "Authorization persistence drift."
            )
            return False, blocked

        if record.get("execution_performed") is not False:
            blocked["reason"] = (
                "Authorization execution state drift."
            )
            return False, blocked

        # Consume exactly once.
        record["consumed"] = True
        record[
            "authorized_for_trust_anchor_rebootstrap"
        ] = False
        record["authorization_status"] = (
            "CONSUMED - "
            + AUTHORIZATION_STATUS
        )

        consumed = deepcopy(record)
        consumed["reason"] = (
            "One-shot rebootstrap authorization "
            "consumed."
        )

        return True, consumed
