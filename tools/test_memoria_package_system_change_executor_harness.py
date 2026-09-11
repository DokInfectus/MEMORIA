#!/usr/bin/env python3
from __future__ import annotations

import builtins
import hashlib
from copy import deepcopy
from pathlib import Path

import memoria_package_system_change_executor_harness as harness

from memoria_package_approval_handoff import plan_sha256
from memoria_package_transaction_approval import (
    build_transaction_approval_receipt,
)
from memoria_package_execution_flow import (
    run_package_execution_flow,
)
from memoria_package_install_plan import (
    build_installation_plan,
)
from memoria_package_system_change_authorization import (
    OneShotSystemChangeAuthorizationStore,
)


ROOT = Path(__file__).resolve().parents[1]

PROTECTED_FILES = [
    ROOT / "tools" / "memoria_package_executor.py",
    ROOT / "tools" / "memoria_package_system_change_authorization.py",
    ROOT / "tools" / "memoria_package_execution_flow.py",
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


class FakeRunner:
    memoria_test_runner = True

    def __init__(
        self,
        *,
        returncode: int = 0,
        exception: Exception | None = None,
    ) -> None:
        self.returncode = returncode
        self.exception = exception
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(list(argv))

        if self.exception is not None:
            raise self.exception

        return self.returncode


before = hashes()

flow = approved_flow()


def transaction_preview_for(
    current_plan,
    transaction_sha: str = "c" * 64,
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
            "Inst memoria-harness-package (1.0)",
            "Conf memoria-harness-package (1.0)",
        ],
        "removal_lines": [],
    }


def fake_preview_builder(
    _feature_profile,
    current_plan,
):
    return 0, transaction_preview_for(current_plan)


original_preview_builder = harness._build_preview_for_plan
harness._build_preview_for_plan = fake_preview_builder


def issued(token: str):
    plan = build_installation_plan("matrix-ui+ocr")

    store = OneShotSystemChangeAuthorizationStore(
        token_factory=lambda: token
    )

    preview = transaction_preview_for(plan)

    approval_receipt = (
        build_transaction_approval_receipt(
            plan,
            preview,
        )
    )

    authorization = store.issue(
        flow,
        plan,
        preview,
        approval_receipt,
    )

    return plan, store, authorization


# Happy path
plan, store, authorization = issued("harness-happy")
runner = FakeRunner()

status, result = harness.run_test_execution_attempt(
    "matrix-ui+ocr",
    store,
    authorization,
    runner,
)

assert status == 0
assert result["harness_status"] == "TEST RUNNER RETURNED"
assert result["authorization_consumed"] is True
assert result["test_runner_invoked"] is True
assert result["runner_returncode"] == 0
assert result["execution_performed"] is False
assert result["system_change_allowed"] is False
assert runner.calls == [plan["command_argv"]]

ok("Happy marked test-runner attempt GREEN")


# Replay
replay_runner = FakeRunner()

status, result = harness.run_test_execution_attempt(
    "matrix-ui+ocr",
    store,
    authorization,
    replay_runner,
)

assert status == 5
assert result["harness_status"] == "BLOCKED"
assert result["authorization_consumed"] is True
assert result["test_runner_invoked"] is False
assert replay_runner.calls == []

ok("Consumed authorization replay fails closed")


# Unmarked runner must not consume
plan, store, authorization = issued("unmarked-runner")

def unmarked_runner(_argv):
    raise AssertionError("Unmarked runner must never run")

status, result = harness.run_test_execution_attempt(
    "matrix-ui+ocr",
    store,
    authorization,
    unmarked_runner,
)

assert status == 5
assert result["authorization_consumed"] is False
assert result["test_runner_invoked"] is False

allowed, _ = store.verify_and_consume(
    authorization,
    plan,
    transaction_preview_for(plan),
)
assert allowed is True

ok("Unmarked runner blocked before consume")


# Preflight failure must not consume
plan, store, authorization = issued("preflight-block")
runner = FakeRunner()

original_preflight = (
    harness.verify_local_executor_prerequisites
)

try:
    harness.verify_local_executor_prerequisites = (
        lambda _plan: {
            "verified": False,
            "executor_status": "BLOCKED",
            "system_change_allowed": False,
            "execution_performed": False,
            "held_package_locks": [
                "/var/lib/dpkg/lock-frontend"
            ],
            "reason": "Synthetic held package lock.",
        }
    )

    status, result = harness.run_test_execution_attempt(
        "matrix-ui+ocr",
        store,
        authorization,
        runner,
    )
finally:
    harness.verify_local_executor_prerequisites = (
        original_preflight
    )

assert status == 5
assert result["authorization_consumed"] is False
assert result["test_runner_invoked"] is False
assert runner.calls == []

allowed, _ = store.verify_and_consume(
    authorization,
    plan,
    transaction_preview_for(plan),
)
assert allowed is True

ok("Preflight failure leaves one-shot unused")


# Non-zero runner return consumes pass permanently
_plan, store, authorization = issued("runner-nonzero")
runner = FakeRunner(returncode=100)

status, result = harness.run_test_execution_attempt(
    "matrix-ui+ocr",
    store,
    authorization,
    runner,
)

assert status == 10
assert result["authorization_consumed"] is True
assert result["test_runner_invoked"] is True
assert result["runner_returncode"] == 100
assert len(runner.calls) == 1

retry_runner = FakeRunner()

status, retry = harness.run_test_execution_attempt(
    "matrix-ui+ocr",
    store,
    authorization,
    retry_runner,
)

assert status == 5
assert retry["test_runner_invoked"] is False
assert retry_runner.calls == []

ok("Non-zero attempt consumes pass and has no retry")


# Runner exception also consumes pass permanently
_plan, store, authorization = issued("runner-exception")
runner = FakeRunner(
    exception=RuntimeError("synthetic runner failure")
)

status, result = harness.run_test_execution_attempt(
    "matrix-ui+ocr",
    store,
    authorization,
    runner,
)

assert status == 11
assert result["authorization_consumed"] is True
assert result["test_runner_invoked"] is True
assert len(runner.calls) == 1

retry_runner = FakeRunner()

status, retry = harness.run_test_execution_attempt(
    "matrix-ui+ocr",
    store,
    authorization,
    retry_runner,
)

assert status == 5
assert retry["test_runner_invoked"] is False
assert retry_runner.calls == []

ok("Runner exception consumes pass and has no retry")


# Fresh-plan tamper must fail before runner
plan, store, authorization = issued("fresh-plan-tamper")
runner = FakeRunner()

def changed_plan(_feature: str):
    changed = deepcopy(plan)
    changed["packages"].append("kraki-filet-fisch")
    changed["package_count"] += 1
    changed["command_argv"].append("kraki-filet-fisch")
    return changed

status, result = harness.run_test_execution_attempt(
    "matrix-ui+ocr",
    store,
    authorization,
    runner,
    plan_builder=changed_plan,
)

assert status == 5
assert result["test_runner_invoked"] is False
assert result["authorization_consumed"] is False
assert runner.calls == []

allowed, _ = store.verify_and_consume(
    authorization,
    plan,
    transaction_preview_for(plan),
)
assert allowed is True

ok("Fresh-plan tamper fails before runner")


# Transaction drift revokes authorization before test runner
plan, store, authorization = issued(
    "transaction-preview-change"
)
runner = FakeRunner()

def changed_preview_builder(
    _feature_profile,
    current_plan,
):
    return 0, transaction_preview_for(
        current_plan,
        transaction_sha="d" * 64,
    )

harness._build_preview_for_plan = changed_preview_builder

status, result = harness.run_test_execution_attempt(
    "matrix-ui+ocr",
    store,
    authorization,
    runner,
)

assert status == 5
assert result["authorization_consumed"] is False
assert result["test_runner_invoked"] is False
assert runner.calls == []
assert "revok" in result["reason"].lower()

# The originally approved transaction coming back later
# must not resurrect the authorization.
allowed, revoked = store.verify_and_consume(
    authorization,
    plan,
    transaction_preview_for(plan),
)

assert allowed is False
assert revoked["consumed"] is False
assert revoked["revoked"] is True
assert (
    revoked["authorization_status"]
    == "REVOKED - TRANSACTION DRIFT"
)

ok(
    "Transaction preview drift permanently revokes "
    "authorization before test runner"
)

harness._build_preview_for_plan = fake_preview_builder

# Restore production preview builder after synthetic tests.
harness._build_preview_for_plan = original_preview_builder


after = hashes()

assert before == after, (
    "Harness regression modified protected product files"
)

ok("Regression changed no protected product file")


source = (
    ROOT
    / "tools"
    / "memoria_package_system_change_executor_harness.py"
).read_text(
    encoding="utf-8"
)

for forbidden in (
    "subprocess",
    "Popen",
    "os.system",
    "os.exec",
    "shell=True",
):
    assert forbidden not in source, (
        f"Forbidden harness marker: {forbidden}"
    )

ok("Harness contains no process execution implementation")

print()
print(
    "MEMORIA System-Change Executor Harness "
    "V0.1 Regression Test GREEN"
)
