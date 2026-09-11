#!/usr/bin/env python3
from __future__ import annotations

import builtins
import hashlib
from copy import deepcopy
from pathlib import Path

from memoria_package_approval_handoff import plan_sha256
from memoria_package_execution_flow import (
    run_package_execution_flow,
)
from memoria_package_install_plan import (
    build_installation_plan,
)
from memoria_package_transaction_approval import (
    build_transaction_approval_receipt,
)
from memoria_package_system_change_authorization import (
    OneShotSystemChangeAuthorizationStore,
)


ROOT = Path(__file__).resolve().parents[1]

PROTECTED_FILES = [
    ROOT / "tools" / "memoria_package_system_change_authorization.py",
    ROOT / "tools" / "memoria_package_execution_flow.py",
    ROOT / "tools" / "memoria_package_executor.py",
    ROOT / "tools" / "memoria_package_execution_gate.py",
    ROOT / "tools" / "memoria_package_install_plan.py",
    ROOT / "tools" / "memoria_package_satisfaction.py",
    ROOT / "scripts" / "install.sh",
]


def ok(message: str) -> None:
    print(f"OK  {message}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes() -> dict[Path, str]:
    return {path: sha256(path) for path in PROTECTED_FILES}


def missing_package_satisfaction(feature: str):
    return {
        "feature_profile": feature,
        "satisfaction_status": "MISSING",
    }


def approved_flow():
    answers = iter(["ja", "ja"])
    original_input = builtins.input

    try:
        builtins.input = lambda _prompt="": next(answers)

        status, result = run_package_execution_flow(
            "matrix-ui+ocr",
            satisfaction_evaluator=(
                missing_package_satisfaction
            ),
        )
    finally:
        builtins.input = original_input

    assert status == 0
    assert result["flow_status"] == "DRY RUN VERIFIED"

    return result


before = hashes()

plan = build_installation_plan("matrix-ui+ocr")
flow = approved_flow()


def transaction_preview_for(
    current_plan,
    transaction_sha: str = "a" * 64,
):
    return {
        "schema_version": (
            "memoria-package-transaction-preview-v0.1"
        ),
        "preview_status": "TRANSACTION PREVIEW VERIFIED",
        "approvable": True,
        "system_change_allowed": False,
        "execution_performed": False,
        "simulation_performed": True,
        "plan_sha256": plan_sha256(current_plan),
        "transaction_sha256": transaction_sha,
        "operation_lines": [
            "Inst memoria-test-package (1.0)",
            "Conf memoria-test-package (1.0)",
        ],
        "removal_lines": [],
    }


preview = transaction_preview_for(plan)

approval_receipt = build_transaction_approval_receipt(
    plan,
    preview,
)


# ------------------------------------------------------------
# Happy One-Shot
# ------------------------------------------------------------

store = OneShotSystemChangeAuthorizationStore(
    token_factory=lambda: "one-shot-happy"
)

authorization = store.issue(
    flow,
    plan,
    preview,
    approval_receipt,
)

allowed, consumed = store.verify_and_consume(
    authorization,
    plan,
    preview,
)

assert allowed is True
assert consumed["consumed"] is True
assert consumed["execution_performed"] is False

ok("Happy one-shot GREEN")


# ------------------------------------------------------------
# Replay einer Kopie
# ------------------------------------------------------------

store = OneShotSystemChangeAuthorizationStore(
    token_factory=lambda: "one-shot-replay"
)

authorization = store.issue(
    flow,
    plan,
    preview,
    approval_receipt,
)
copy_pass = deepcopy(authorization)

first_ok, _ = store.verify_and_consume(
    authorization,
    plan,
    preview,
)

second_ok, result = store.verify_and_consume(
    copy_pass,
    plan,
    preview,
)

assert first_ok is True
assert second_ok is False
assert result["consumed"] is True

ok("Copied authorization replay fails closed")


# ------------------------------------------------------------
# Authorization manipuliert
# ------------------------------------------------------------

store = OneShotSystemChangeAuthorizationStore(
    token_factory=lambda: "one-shot-tamper"
)

authorization = store.issue(
    flow,
    plan,
    preview,
    approval_receipt,
)
tampered = deepcopy(authorization)
tampered["package_count"] = 489

allowed, result = store.verify_and_consume(
    tampered,
    plan,
    preview,
)

assert allowed is False
assert result["authorization_status"] == "BLOCKED"

ok("Authorization tamper fails closed")


# ------------------------------------------------------------
# Unbekannter Token
# ------------------------------------------------------------

store = OneShotSystemChangeAuthorizationStore(
    token_factory=lambda: "known-token"
)

authorization = store.issue(
    flow,
    plan,
    preview,
    approval_receipt,
)
unknown = deepcopy(authorization)
unknown["token_id"] = "kraki-vip-faelschung"

allowed, result = store.verify_and_consume(
    unknown,
    plan,
    preview,
)

assert allowed is False
assert "Unknown" in result["reason"]

ok("Unknown token fails closed")


# ------------------------------------------------------------
# Doppelter Token darf nicht ausgegeben werden
# ------------------------------------------------------------

store = OneShotSystemChangeAuthorizationStore(
    token_factory=lambda: "duplicate-token"
)

store.issue(
    flow,
    plan,
    preview,
    approval_receipt,
)

try:
    store.issue(
    flow,
    plan,
    preview,
    approval_receipt,
)
except ValueError as exc:
    assert "duplicate" in str(exc)
else:
    raise AssertionError(
        "Duplicate one-shot token was accepted"
    )

ok("Duplicate token issue fails closed")


# ------------------------------------------------------------
# Planänderung nach Ausgabe
# ------------------------------------------------------------

store = OneShotSystemChangeAuthorizationStore(
    token_factory=lambda: "plan-change"
)

authorization = store.issue(
    flow,
    plan,
    preview,
    approval_receipt,
)

changed = deepcopy(plan)
changed["packages"].append("kraki-filet-fisch")
changed["package_count"] += 1
changed["command_argv"].append("kraki-filet-fisch")

allowed, result = store.verify_and_consume(
    authorization,
    changed,
    transaction_preview_for(changed),
)

assert allowed is False
assert result["authorization_status"] == "BLOCKED"

ok("Plan change after issue fails closed")


# ------------------------------------------------------------
# Gefälschter Flow darf keinen Pass erzeugen
# ------------------------------------------------------------

fake_flow = deepcopy(flow)
fake_flow["flow_status"] = "KRAKI VERIFIED"

store = OneShotSystemChangeAuthorizationStore(
    token_factory=lambda: "fake-flow"
)

try:
    store.issue(
        fake_flow,
        plan,
        preview,
        approval_receipt,
    )
except ValueError:
    pass
else:
    raise AssertionError(
        "Ineligible flow received authorization"
    )

ok("Forged flow fails closed")


# ------------------------------------------------------------
# Bereits ungeeigneter Plan darf keinen Pass erhalten
# ------------------------------------------------------------

bad_plan = deepcopy(plan)
bad_plan["package_manager"] = "kraki-pkg"

store = OneShotSystemChangeAuthorizationStore(
    token_factory=lambda: "bad-plan"
)

try:
    bad_preview = transaction_preview_for(
        bad_plan
    )
    bad_receipt = build_transaction_approval_receipt(
        bad_plan,
        bad_preview,
    )

    store.issue(
        flow,
        bad_plan,
        bad_preview,
        bad_receipt,
    )
except ValueError:
    pass
else:
    raise AssertionError(
        "Ineligible plan received authorization"
    )

ok("Ineligible plan fails closed")


# ------------------------------------------------------------
# Transaction drift permanently revokes old authorization
# ------------------------------------------------------------

store = OneShotSystemChangeAuthorizationStore(
    token_factory=lambda: "transaction-change"
)

authorization = store.issue(
    flow,
    plan,
    preview,
    approval_receipt,
)

assert authorization["consumed"] is False
assert authorization["revoked"] is False
assert authorization["revocation_reason"] is None

changed_preview = transaction_preview_for(
    plan,
    transaction_sha="b" * 64,
)

allowed, result = store.verify_and_consume(
    authorization,
    plan,
    changed_preview,
)

assert allowed is False
assert result["consumed"] is False
assert result["revoked"] is True
assert result["revocation_reason"] == "TRANSACTION DRIFT"
assert (
    result["authorization_status"]
    == "REVOKED - TRANSACTION DRIFT"
)
assert "permanently revoked" in result["reason"].lower()

# Returning to the exact originally approved transaction
# must NEVER resurrect the old authorization.
allowed, revoked_again = store.verify_and_consume(
    authorization,
    plan,
    preview,
)

assert allowed is False
assert revoked_again["consumed"] is False
assert revoked_again["revoked"] is True
assert (
    revoked_again["revocation_reason"]
    == "TRANSACTION DRIFT"
)
assert (
    revoked_again["authorization_status"]
    == "REVOKED - TRANSACTION DRIFT"
)

# A changed transaction is still allowed through the normal
# sovereignty path: fresh exact approval + fresh one-shot.
fresh_receipt = build_transaction_approval_receipt(
    plan,
    changed_preview,
)

fresh_store = OneShotSystemChangeAuthorizationStore(
    token_factory=lambda: "transaction-change-fresh"
)

fresh_authorization = fresh_store.issue(
    flow,
    plan,
    changed_preview,
    fresh_receipt,
)

assert fresh_authorization["revoked"] is False
assert fresh_authorization["consumed"] is False

allowed, consumed = fresh_store.verify_and_consume(
    fresh_authorization,
    plan,
    changed_preview,
)

assert allowed is True
assert consumed["consumed"] is True
assert consumed["revoked"] is False
assert consumed["revocation_reason"] is None
assert (
    consumed["transaction_sha256"]
    == changed_preview["transaction_sha256"]
)

ok(
    "Transaction drift permanently revokes old authorization; "
    "fresh exact approval creates a new usable one-shot"
)


# ------------------------------------------------------------
# Non-approvable preview must not receive authorization
# ------------------------------------------------------------

blocked_preview = deepcopy(preview)
blocked_preview["approvable"] = False
blocked_preview["preview_status"] = (
    "BLOCKED - PACKAGE REMOVAL PRESENT"
)
blocked_preview["removal_lines"] = [
    "Remv kraki-filet-fisch [9.9]"
]

store = OneShotSystemChangeAuthorizationStore(
    token_factory=lambda: "blocked-preview"
)

try:
    store.issue(
        flow,
        plan,
        blocked_preview,
        approval_receipt,
    )
except ValueError:
    pass
else:
    raise AssertionError(
        "Non-approvable transaction preview received "
        "system-change authorization"
    )

ok("Non-approvable transaction preview fails closed")


# ------------------------------------------------------------
# Forged transaction approval receipt
# ------------------------------------------------------------

forged_receipt = deepcopy(approval_receipt)
forged_receipt["transaction_sha256"] = "f" * 64

store = OneShotSystemChangeAuthorizationStore(
    token_factory=lambda: "forged-transaction-approval"
)

try:
    store.issue(
        flow,
        plan,
        preview,
        forged_receipt,
    )
except ValueError as exc:
    assert "transaction approval" in str(exc).lower()
else:
    raise AssertionError(
        "Forged transaction approval receipt "
        "received one-shot authorization"
    )

ok("Forged transaction approval receipt fails closed")


# ------------------------------------------------------------
# Missing transaction approval receipt
# ------------------------------------------------------------

store = OneShotSystemChangeAuthorizationStore(
    token_factory=lambda: "missing-transaction-approval"
)

try:
    store.issue(
        flow,
        plan,
        preview,
        {},
    )
except ValueError:
    pass
else:
    raise AssertionError(
        "Missing transaction approval receipt "
        "received one-shot authorization"
    )

ok("Missing transaction approval receipt fails closed")


# ------------------------------------------------------------
# Produktdateien unverändert
# ------------------------------------------------------------

after = hashes()

assert before == after, (
    "One-Shot regression modified protected product files"
)

ok("Regression changed no protected product file")


# ------------------------------------------------------------
# Keine Ausführungs-/Persistenzlogik
# ------------------------------------------------------------

source = (
    ROOT
    / "tools"
    / "memoria_package_system_change_authorization.py"
).read_text(encoding="utf-8")

for forbidden in (
    "subprocess",
    "Popen",
    "os.system",
    "os.exec",
    "apt-get update",
    "systemctl",
    "json.dump",
    "write_text",
    "write_bytes",
):
    assert forbidden not in source, (
        f"Forbidden authorization marker: {forbidden}"
    )

ok("Authorization contains no execution or persistence logic")


print()
print(
    "MEMORIA System Change One-Shot Authorization "
    "V0.1 Regression Test GREEN"
)
