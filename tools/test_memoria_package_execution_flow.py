#!/usr/bin/env python3
from __future__ import annotations

import builtins
import hashlib
from copy import deepcopy
from pathlib import Path

from memoria_package_execution_flow import (
    run_package_execution_flow,
)
from memoria_package_install_plan import (
    build_installation_plan,
)


ROOT = Path(__file__).resolve().parents[1]

PROTECTED_FILES = [
    ROOT / "tools" / "memoria_package_execution_flow.py",
    ROOT / "tools" / "memoria_package_execution_gate.py",
    ROOT / "tools" / "memoria_package_executor.py",
    ROOT / "tools" / "memoria_package_approval_handoff.py",
    ROOT / "tools" / "memoria_package_install_plan.py",
    ROOT / "tools" / "memoria_package_satisfaction.py",
    ROOT / "scripts" / "install.sh",
]


def ok(message: str) -> None:
    print(f"OK  {message}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes() -> dict[Path, str]:
    return {
        path: sha256(path)
        for path in PROTECTED_FILES
    }


def fixed_satisfaction(status: str):
    def evaluate(feature: str):
        return {
            "feature_profile": feature,
            "satisfaction_status": status,
        }

    return evaluate


def run_with_answers(
    feature: str,
    answers: list[str],
    *,
    plan_builder=build_installation_plan,
    satisfaction_evaluator=fixed_satisfaction(
        "NOT APPLICABLE"
    ),
):
    iterator = iter(answers)
    original_input = builtins.input

    try:
        builtins.input = lambda _prompt="": next(iterator)

        return run_package_execution_flow(
            feature,
            plan_builder=plan_builder,
            satisfaction_evaluator=satisfaction_evaluator,
        )
    finally:
        builtins.input = original_input


before = hashes()


# ------------------------------------------------------------
# SATISFIED short-circuits before the execution gate
# ------------------------------------------------------------

for feature in (
    "local-ocr",
    "matrix-ui+ocr",
):
    status, result = run_with_answers(
        feature,
        [],
        satisfaction_evaluator=fixed_satisfaction(
            "SATISFIED"
        ),
    )

    assert status == 0
    assert result["flow_status"] == "NOT REQUIRED"
    assert result["system_change_allowed"] is False
    assert result["execution_performed"] is False
    assert result["executor_result"] is None
    assert (
        result["satisfaction_result"][
            "satisfaction_status"
        ]
        == "SATISFIED"
    )

ok("SATISFIED short-circuits before execution gate")


# ------------------------------------------------------------
# Non-SATISFIED states keep the existing gate path
# ------------------------------------------------------------

for satisfaction_status in (
    "PARTIAL",
    "MISSING",
    "UNKNOWN",
):
    status, result = run_with_answers(
        "matrix-ui+ocr",
        ["nein"],
        satisfaction_evaluator=fixed_satisfaction(
            satisfaction_status
        ),
    )

    assert status != 0
    assert result["flow_status"] == "BLOCKED"
    assert result["execution_performed"] is False

ok("PARTIAL/MISSING/UNKNOWN keep existing gate path")


# ------------------------------------------------------------
# Minimal base dependency
# ------------------------------------------------------------

status, result = run_with_answers(
    "minimal",
    ["ja", "ja"],
)

assert status == 0
assert result["flow_status"] == "DRY RUN VERIFIED"
assert result["system_change_allowed"] is False
assert result["execution_performed"] is False

executor_result = result["executor_result"]

assert executor_result is not None
assert executor_result["verified"] is True
assert executor_result["executor_status"] == "DRY RUN VERIFIED"
assert executor_result["system_change_allowed"] is False
assert executor_result["execution_performed"] is False

ok("Minimal gpgv approval flow GREEN")


# ------------------------------------------------------------
# Initial approval decline
# ------------------------------------------------------------

status, result = run_with_answers(
    "matrix-ui+ocr",
    ["nein"],
)

assert status != 0
assert result["flow_status"] == "BLOCKED"
assert result["system_change_allowed"] is False
assert result["execution_performed"] is False

ok("Initial approval decline fails closed")


# ------------------------------------------------------------
# Final authorization decline
# ------------------------------------------------------------

status, result = run_with_answers(
    "matrix-ui+ocr",
    ["ja", "nein"],
)

assert status != 0
assert result["flow_status"] == "BLOCKED"
assert result["system_change_allowed"] is False
assert result["execution_performed"] is False

ok("Final authorization decline fails closed")


# ------------------------------------------------------------
# Happy same-process chain
# ------------------------------------------------------------

status, result = run_with_answers(
    "matrix-ui+ocr",
    ["ja", "ja"],
)

assert status == 0
assert result["flow_status"] == "DRY RUN VERIFIED"
assert result["system_change_allowed"] is False
assert result["execution_performed"] is False

executor_result = result["executor_result"]

assert executor_result is not None
assert executor_result["verified"] is True
assert executor_result["executor_status"] == "DRY RUN VERIFIED"
assert executor_result["system_change_allowed"] is False
assert executor_result["execution_performed"] is False

ok("Happy same-process flow GREEN")


# ------------------------------------------------------------
# Manipulation erst beim dritten Plan-Build
# ------------------------------------------------------------

base = build_installation_plan("matrix-ui+ocr")
calls = 0


def third_build_tamper(_feature: str):
    global calls
    calls += 1

    plan = deepcopy(base)

    if calls == 3:
        fish = "kraki-filet-fisch"
        plan["packages"].append(fish)
        plan["package_count"] += 1
        plan["command_argv"].append(fish)

    return plan


status, result = run_with_answers(
    "matrix-ui+ocr",
    ["ja", "ja"],
    plan_builder=third_build_tamper,
)

assert calls == 3
assert status != 0
assert result["flow_status"] == "BLOCKED"
assert result["system_change_allowed"] is False
assert result["execution_performed"] is False

executor_result = result["executor_result"]

assert executor_result is not None
assert executor_result["verified"] is False
assert executor_result["executor_status"] == "BLOCKED"

ok("Third plan build tamper fails closed")


# ------------------------------------------------------------
# Geschützte Produktdateien unverändert
# ------------------------------------------------------------

after = hashes()

assert before == after, (
    "Package Execution Flow regression modified protected files"
)

ok("Regression changed no protected product file")


# ------------------------------------------------------------
# Static Safety
# ------------------------------------------------------------

source = (
    ROOT
    / "tools"
    / "memoria_package_execution_flow.py"
).read_text(
    encoding="utf-8",
)

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
        f"Forbidden flow marker: {forbidden}"
    )

ok("Flow contains no execution or authorization persistence logic")


print()
print(
    "MEMORIA Package Execution Flow "
    "V0.1 Regression Test GREEN"
)
