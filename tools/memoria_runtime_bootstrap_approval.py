#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import secrets
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from memoria_runtime_bootstrap_plan import (
    CANONICAL_BOOTSTRAP_TARGET,
    CANONICAL_IDENTITY_TARGET,
    CANONICAL_LAUNCHER_TARGET,
    CANONICAL_RELEASE_BASE,
    CONTEXT_SCHEMA,
    EXPECTED_FINGERPRINT,
    REQUIRED_PAYLOAD_SOURCES,
    SCHEMA_VERSION as PLAN_SCHEMA,
    verify_runtime_bootstrap_plan_identity,
)


SCHEMA_VERSION = (
    "memoria-runtime-bootstrap-approval-v0.1"
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


def _canonical_sha256(
    value: dict[str, Any],
) -> str:
    data = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    return hashlib.sha256(data).hexdigest()


def _hash_map_is_exact(
    value: Any,
    expected_keys: set[str],
) -> bool:
    if not isinstance(value, dict):
        return False

    if set(value) != expected_keys:
        return False

    return all(
        _is_sha256(digest)
        for digest in value.values()
    )


def runtime_bootstrap_plan_is_approvable(
    plan: dict[str, Any],
) -> bool:
    if not isinstance(plan, dict):
        return False

    if (
        plan.get("schema_version") != PLAN_SCHEMA
        or plan.get("plan_status")
        != "READY FOR APPROVAL"
        or plan.get("approvable") is not True
        or not _is_sha256(
            plan.get("plan_sha256")
        )
        or not verify_runtime_bootstrap_plan_identity(
            plan
        )
    ):
        return False

    release = plan.get("active_release")

    if not isinstance(release, str) or not release:
        return False

    context = plan.get("bundle_context")

    if not isinstance(context, dict):
        return False

    if set(context) != {
        "schema_version",
        "active_release",
        "bundle_dir",
        "project_root",
    }:
        return False

    if context.get("schema_version") != CONTEXT_SCHEMA:
        return False

    if context.get("active_release") != release:
        return False

    bundle_dir = context.get("bundle_dir")
    project_root = context.get("project_root")

    if (
        not isinstance(bundle_dir, str)
        or not bundle_dir
        or not Path(bundle_dir).is_absolute()
    ):
        return False

    if (
        not isinstance(project_root, str)
        or not project_root
        or not Path(project_root).is_absolute()
    ):
        return False

    if plan.get("bundle_dir") != bundle_dir:
        return False

    if plan.get("project_root") != project_root:
        return False

    if plan.get("bundle_context_sha256") != (
        _canonical_sha256(context)
    ):
        return False

    if plan.get("signer_fingerprint") != (
        EXPECTED_FINGERPRINT
    ):
        return False

    if plan.get("release_state_target") != str(
        CANONICAL_RELEASE_BASE / release
    ):
        return False

    if plan.get("bootstrap_target") != str(
        CANONICAL_BOOTSTRAP_TARGET
    ):
        return False

    if plan.get("launcher_target") != str(
        CANONICAL_LAUNCHER_TARGET
    ):
        return False

    if plan.get("identity_target") != str(
        CANONICAL_IDENTITY_TARGET
    ):
        return False

    allowed_stage_states = {
        "ABSENT",
        "ALREADY STAGED",
    }

    if (
        plan.get("release_state_target_state")
        not in allowed_stage_states
    ):
        return False

    if (
        plan.get("bootstrap_target_state")
        not in allowed_stage_states
    ):
        return False

    if (
        plan.get("launcher_target_state")
        not in allowed_stage_states
    ):
        return False

    if plan.get("identity_target_state") != "ABSENT":
        return False

    source_hashes = plan.get("source_hashes")

    if not _hash_map_is_exact(
        source_hashes,
        set(REQUIRED_PAYLOAD_SOURCES),
    ):
        return False

    manifest_name = (
        f"MEMORIA-{release}.payload.sha256"
    )

    release_hashes = plan.get(
        "release_state_hashes"
    )

    if not _hash_map_is_exact(
        release_hashes,
        {
            "SHA256SUMS",
            "SHA256SUMS.sig",
            manifest_name,
        },
    ):
        return False

    return True


def _bound_identity(
    plan: dict[str, Any],
) -> dict[str, Any]:
    fields = (
        "plan_sha256",
        "bundle_context_sha256",
        "active_release",
        "bundle_context",
        "bundle_dir",
        "project_root",
        "signer_fingerprint",
        "release_state_target",
        "release_state_target_state",
        "bootstrap_target",
        "bootstrap_target_state",
        "launcher_target",
        "launcher_target_state",
        "identity_target",
        "identity_target_state",
        "source_hashes",
        "release_state_hashes",
    )

    return {
        field: deepcopy(plan.get(field))
        for field in fields
    }


def build_runtime_bootstrap_approval_receipt(
    plan: dict[str, Any],
    *,
    approval_id: str,
) -> dict[str, Any]:
    if not runtime_bootstrap_plan_is_approvable(
        plan
    ):
        raise ValueError(
            "runtime-bootstrap plan is not eligible "
            "for explicit approval"
        )

    if (
        not isinstance(approval_id, str)
        or not approval_id
    ):
        raise ValueError(
            "invalid approval identity"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "approval_id": approval_id,
        "approved": True,
        "approval_status": (
            "EXACT RUNTIME BOOTSTRAP PLAN APPROVED"
        ),
        "persistence": "MEMORY ONLY",
        "system_change_allowed": False,
        "execution_performed": False,
        "bound_identity":
            _bound_identity(plan),
    }


def verify_runtime_bootstrap_approval_receipt(
    receipt: dict[str, Any],
    plan: dict[str, Any],
) -> bool:
    if not runtime_bootstrap_plan_is_approvable(
        plan
    ):
        return False

    if not isinstance(receipt, dict):
        return False

    if receipt.get("schema_version") != (
        SCHEMA_VERSION
    ):
        return False

    approval_id = receipt.get("approval_id")

    if (
        not isinstance(approval_id, str)
        or not approval_id
    ):
        return False

    if receipt.get("approved") is not True:
        return False

    if receipt.get("approval_status") != (
        "EXACT RUNTIME BOOTSTRAP PLAN APPROVED"
    ):
        return False

    if receipt.get("persistence") != (
        "MEMORY ONLY"
    ):
        return False

    if receipt.get(
        "system_change_allowed"
    ) is not False:
        return False

    if receipt.get(
        "execution_performed"
    ) is not False:
        return False

    return receipt.get(
        "bound_identity"
    ) == _bound_identity(plan)


class RuntimeBootstrapApprovalStore:
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
        self._approval_id_factory = (
            approval_id_factory
        )

        self._records: dict[
            str,
            dict[str, Any],
        ] = {}

    def issue(
        self,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        if not runtime_bootstrap_plan_is_approvable(
            plan
        ):
            raise ValueError(
                "runtime-bootstrap plan is not eligible "
                "for explicit approval"
            )

        approval_id = (
            self._approval_id_factory()
        )

        if (
            not isinstance(approval_id, str)
            or not approval_id
        ):
            raise ValueError(
                "approval id factory returned "
                "invalid identity"
            )

        if approval_id in self._records:
            raise ValueError(
                "duplicate approval identity"
            )

        receipt = (
            build_runtime_bootstrap_approval_receipt(
                plan,
                approval_id=approval_id,
            )
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
        if not (
            verify_runtime_bootstrap_approval_receipt(
                receipt,
                plan,
            )
        ):
            return False

        approval_id = receipt.get(
            "approval_id"
        )

        record = self._records.get(
            approval_id
        )

        if record is None:
            return False

        if record.get(
            "authorization_claimed"
        ) is True:
            return False

        return receipt == record.get(
            "receipt"
        )

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

        record[
            "authorization_claimed"
        ] = True

        return True


def print_runtime_bootstrap_plan_for_approval(
    plan: dict[str, Any],
) -> None:
    print(
        "MEMORIA RUNTIME BOOTSTRAP APPROVAL V0.1"
    )
    print("-" * 64)
    print(
        f"Release: {plan['active_release']}"
    )
    print(
        f"Bundle: {plan['bundle_dir']}"
    )
    print(
        f"Project Root: {plan['project_root']}"
    )
    print(
        "Signer Fingerprint: "
        f"{plan['signer_fingerprint']}"
    )
    print(
        "Release State: "
        f"{plan['release_state_target']} "
        f"[{plan['release_state_target_state']}]"
    )
    print(
        "Bootstrap Verifier: "
        f"{plan['bootstrap_target']} "
        f"[{plan['bootstrap_target_state']}]"
    )
    print(
        "Launcher: "
        f"{plan['launcher_target']} "
        f"[{plan['launcher_target_state']}]"
    )
    print(
        "Installed Identity: "
        f"{plan['identity_target']} "
        f"[{plan['identity_target_state']}]"
    )
    print(
        f"Plan SHA-256: {plan['plan_sha256']}"
    )
    print(
        "System Change Allowed: no"
    )
    print(
        "Approval Persistence: MEMORY ONLY"
    )


def request_runtime_bootstrap_approval(
    plan: dict[str, Any],
    approval_store: RuntimeBootstrapApprovalStore,
) -> tuple[int, dict[str, Any] | None]:
    if not runtime_bootstrap_plan_is_approvable(
        plan
    ):
        print(
            "RUNTIME BOOTSTRAP APPROVAL BLOCKED"
        )
        print(
            "Plan is not approvable."
        )
        print(
            "No system change allowed."
        )

        return 3, None

    print_runtime_bootstrap_plan_for_approval(
        plan
    )

    print()

    answer = input(
        "Exakt diesen Runtime-Bootstrap-Plan "
        "freigeben? / Approve exactly this "
        "runtime-bootstrap plan? [ja/nein]: "
    ).strip().lower()

    if answer not in {
        "ja",
        "j",
        "yes",
        "y",
    }:
        print()
        print(
            "RUNTIME BOOTSTRAP PLAN DECLINED"
        )
        print(
            "Approval receipt: NOT CREATED"
        )
        print(
            "No system change allowed."
        )

        return 1, None

    receipt = approval_store.issue(
        plan
    )

    print()
    print(
        "RUNTIME BOOTSTRAP PLAN APPROVED"
    )
    print(
        "Approved Plan SHA-256: "
        f"{plan['plan_sha256']}"
    )
    print(
        f"Approval ID: {receipt['approval_id']}"
    )
    print(
        "Approval Receipt: CREATED IN MEMORY"
    )
    print(
        "NO RECEIPT FILE WRITTEN"
    )
    print(
        "NO SYSTEM CHANGE PERFORMED"
    )
    print(
        "System change remains BLOCKED."
    )

    return 0, receipt
