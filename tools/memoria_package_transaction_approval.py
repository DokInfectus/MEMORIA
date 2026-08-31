#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from memoria_package_approval_handoff import plan_sha256


SCHEMA_VERSION = (
    "memoria-package-transaction-approval-v0.1"
)

PREVIEW_SCHEMA = (
    "memoria-package-transaction-preview-v0.1"
)


def _is_sha256(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(
            char in "0123456789abcdef"
            for char in value
        )
    )


def transaction_is_approvable(
    current_plan: dict[str, Any],
    transaction_preview: dict[str, Any],
) -> bool:
    if not isinstance(transaction_preview, dict):
        return False

    return bool(
        transaction_preview.get("schema_version")
        == PREVIEW_SCHEMA
        and transaction_preview.get("preview_status")
        == "TRANSACTION PREVIEW VERIFIED"
        and transaction_preview.get("approvable") is True
        and transaction_preview.get(
            "system_change_allowed"
        ) is False
        and transaction_preview.get(
            "execution_performed"
        ) is False
        and transaction_preview.get(
            "simulation_performed"
        ) is True
        and not list(
            transaction_preview.get("removal_lines") or []
        )
        and transaction_preview.get("plan_sha256")
        == plan_sha256(current_plan)
        and _is_sha256(
            transaction_preview.get("transaction_sha256")
        )
    )


def build_transaction_approval_receipt(
    current_plan: dict[str, Any],
    transaction_preview: dict[str, Any],
) -> dict[str, Any]:
    if not transaction_is_approvable(
        current_plan,
        transaction_preview,
    ):
        raise ValueError(
            "transaction preview is not eligible "
            "for explicit user approval"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "approved": True,
        "plan_sha256": plan_sha256(current_plan),
        "transaction_sha256": transaction_preview[
            "transaction_sha256"
        ],
        "feature_profile": current_plan[
            "feature_profile"
        ],
        "platform_profile": current_plan[
            "platform_profile"
        ],
        "package_manager": current_plan[
            "package_manager"
        ],
        "package_count": current_plan[
            "package_count"
        ],
        "approval_status": (
            "EXACT TRANSACTION APPROVED"
        ),
        "persistence": "MEMORY ONLY",
        "system_change_allowed": False,
        "execution_performed": False,
    }


def verify_transaction_approval_receipt(
    receipt: dict[str, Any],
    current_plan: dict[str, Any],
    transaction_preview: dict[str, Any],
) -> bool:
    if not transaction_is_approvable(
        current_plan,
        transaction_preview,
    ):
        return False

    if receipt.get("schema_version") != SCHEMA_VERSION:
        return False

    if receipt.get("approved") is not True:
        return False

    if receipt.get("approval_status") != (
        "EXACT TRANSACTION APPROVED"
    ):
        return False

    if receipt.get("persistence") != "MEMORY ONLY":
        return False

    if receipt.get("system_change_allowed") is not False:
        return False

    if receipt.get("execution_performed") is not False:
        return False

    if receipt.get("plan_sha256") != plan_sha256(
        current_plan
    ):
        return False

    if receipt.get("transaction_sha256") != (
        transaction_preview.get("transaction_sha256")
    ):
        return False

    for field in (
        "feature_profile",
        "platform_profile",
        "package_manager",
        "package_count",
    ):
        if receipt.get(field) != current_plan.get(field):
            return False

    return True


def print_transaction_for_approval(
    current_plan: dict[str, Any],
    transaction_preview: dict[str, Any],
) -> None:
    print("MEMORIA TRANSACTION APPROVAL V0.1")
    print("-" * 64)

    print(
        f"Feature Profile: "
        f"{current_plan['feature_profile']}"
    )
    print(
        f"Platform Profile: "
        f"{current_plan['platform_profile']}"
    )
    print(
        f"Package Manager: "
        f"{current_plan['package_manager']}"
    )
    print()

    print("Resolved APT transaction:")

    operations = list(
        transaction_preview.get("operation_lines") or []
    )

    if operations:
        for line in operations:
            print(f"- {line}")
    else:
        print("- no package operations")

    print()

    summaries = list(
        transaction_preview.get("summary_lines") or []
    )

    if summaries:
        print("APT Summary:")
        for line in summaries:
            print(f"- {line}")
        print()

    print(
        f"Plan SHA-256: "
        f"{plan_sha256(current_plan)}"
    )
    print(
        "Transaction SHA-256: "
        f"{transaction_preview['transaction_sha256']}"
    )
    print("System Change Allowed: no")
    print("Approval Receipt Persistence: MEMORY ONLY")


def request_transaction_approval(
    current_plan: dict[str, Any],
    transaction_preview: dict[str, Any],
) -> tuple[int, dict[str, Any] | None]:
    if not transaction_is_approvable(
        current_plan,
        transaction_preview,
    ):
        print("TRANSACTION APPROVAL BLOCKED")
        print("Transaction preview is not approvable.")
        print("No system change allowed.")
        return 3, None

    print_transaction_for_approval(
        current_plan,
        transaction_preview,
    )

    print()

    answer = input(
        "Exakt diese aufgelöste APT-Transaktion freigeben? "
        "/ Approve exactly this resolved APT transaction? "
        "[ja/nein]: "
    ).strip().lower()

    if answer not in {"ja", "j", "yes", "y"}:
        print()
        print("TRANSACTION DECLINED")
        print("Approval receipt: NOT CREATED")
        print("No system change allowed.")
        return 1, None

    receipt = build_transaction_approval_receipt(
        current_plan,
        transaction_preview,
    )

    print()
    print("TRANSACTION APPROVED")
    print(
        "Approved Transaction SHA-256: "
        f"{receipt['transaction_sha256']}"
    )
    print("Approval Receipt: CREATED IN MEMORY")
    print("NO RECEIPT FILE WRITTEN")
    print("NO INSTALLATION EXECUTED")
    print("System change remains BLOCKED.")

    return 0, receipt
