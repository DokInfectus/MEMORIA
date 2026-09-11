#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path

import memoria_package_system_change_runner as runner_module
from memoria_package_approval_handoff import plan_sha256
from memoria_package_install_plan import (
    build_installation_plan,
)
from memoria_package_system_change_authorization import (
    OneShotSystemChangeAuthorizationStore,
)
from memoria_package_transaction_approval import (
    build_transaction_approval_receipt,
)
from memoria_package_transaction_preview import SAFE_CHILD_ENV


ROOT = Path(__file__).resolve().parents[1]

PROTECTED_FILES = [
    ROOT / "tools" / "memoria_package_system_change_runner.py",
    ROOT / "tools" / "memoria_package_transaction_approval.py",
    ROOT / "tools" / "memoria_package_transaction_preview.py",
    ROOT / "tools" / "memoria_package_system_change_authorization.py",
    ROOT / "tools" / "memoria_package_system_change_executor_harness.py",
    ROOT / "tools" / "memoria_package_executor.py",
    ROOT / "tools" / "memoria_package_execution_flow.py",
    ROOT / "scripts" / "install.sh",
    ROOT / "Release_check.md",
    ROOT / "README.md",
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


def preview_for(
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
            "Inst memoria-runner-test-package (1.0)",
            "Conf memoria-runner-test-package (1.0)",
        ],
        "summary_lines": [],
        "removal_lines": [],
    }


def flow_for(current_plan):
    return {
        "schema_version": (
            "memoria-package-execution-flow-v0.1"
        ),
        "flow_status": "DRY RUN VERIFIED",
        "system_change_allowed": False,
        "execution_performed": False,
        "executor_result": {
            "schema_version": (
                "memoria-package-executor-dry-run-v0.1"
            ),
            "verified": True,
            "executor_status": "DRY RUN VERIFIED",
            "system_change_allowed": False,
            "execution_performed": False,
            "held_package_locks": [],
            "plan_sha256": plan_sha256(current_plan),
        },
    }


def green_preflight(current_plan):
    return {
        "verified": True,
        "executor_status": "LOCAL PREFLIGHT VERIFIED",
        "system_change_allowed": False,
        "execution_performed": False,
        "plan_sha256": plan_sha256(current_plan),
        "reason": "Synthetic GREEN preflight.",
        "held_package_locks": [],
        "apt_get_path": "/usr/bin/apt-get",
    }


def blocked_preflight(current_plan):
    return {
        "verified": False,
        "executor_status": "BLOCKED",
        "system_change_allowed": False,
        "execution_performed": False,
        "plan_sha256": plan_sha256(current_plan),
        "reason": "Synthetic package lock.",
        "held_package_locks": ["/var/lib/dpkg/lock"],
        "apt_get_path": "/usr/bin/apt-get",
    }


class FakeProcessRunner:
    memoria_test_runner = True

    def __init__(
        self,
        *,
        returncode: int = 0,
        output: str = "fake apt output",
        exception: Exception | None = None,
    ):
        self.returncode = returncode
        self.output = output
        self.exception = exception
        self.calls = []

    def __call__(self, argv, env):
        self.calls.append(
            (list(argv), dict(env))
        )

        if self.exception is not None:
            raise self.exception

        return self.returncode, self.output


class UnmarkedRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, env):
        self.calls.append((list(argv), dict(env)))
        return 0, "should never run"


def issued(
    token: str,
    *,
    transaction_sha: str = "c" * 64,
):
    plan = build_installation_plan("matrix-ui+ocr")
    preview = preview_for(
        plan,
        transaction_sha=transaction_sha,
    )
    receipt = build_transaction_approval_receipt(
        plan,
        preview,
    )
    store = OneShotSystemChangeAuthorizationStore(
        token_factory=lambda: token
    )
    authorization = store.issue(
        flow_for(plan),
        plan,
        preview,
        receipt,
    )

    return plan, preview, store, authorization


before = hashes()

original_preflight = (
    runner_module.verify_local_executor_prerequisites
)
original_preview_builder = (
    runner_module._build_preview_for_plan
)

try:
    runner_module.verify_local_executor_prerequisites = (
        green_preflight
    )

    def same_preview(
        _feature_profile,
        current_plan,
    ):
        return 0, preview_for(current_plan)

    runner_module._build_preview_for_plan = same_preview


    # --------------------------------------------------------
    # Happy real-boundary model with FAKE process runner
    # --------------------------------------------------------

    plan, preview, store, authorization = issued(
        "runner-happy"
    )

    fake = FakeProcessRunner(
        returncode=0,
        output="APT TEST OUTPUT",
    )

    status, result = (
        runner_module.run_system_change_attempt(
            "matrix-ui+ocr",
            store,
            authorization,
            process_runner=fake,
        )
    )

    expected_argv = [
        "/usr/bin/apt-get",
        *plan["command_argv"][1:],
    ]

    assert status == 0
    assert result["runner_status"] == "EXECUTION COMPLETED"
    assert result["authorization_consumed"] is True
    assert result["execution_authorized"] is True
    assert result["execution_performed"] is True
    assert result["process_runner_invoked"] is True
    assert result["runner_returncode"] == 0
    assert result["execution_argv"] == expected_argv
    assert result["process_output"] == "APT TEST OUTPUT"

    assert fake.calls == [
        (
            expected_argv,
            dict(SAFE_CHILD_ENV),
        )
    ]

    ok("Happy production-runner boundary GREEN")


    # --------------------------------------------------------
    # Consumed pass cannot execute again
    # --------------------------------------------------------

    replay = FakeProcessRunner()

    status, result = (
        runner_module.run_system_change_attempt(
            "matrix-ui+ocr",
            store,
            authorization,
            process_runner=replay,
        )
    )

    assert status == 5
    assert result["authorization_consumed"] is True
    assert result["process_runner_invoked"] is False
    assert replay.calls == []

    ok("Consumed production authorization replay fails closed")


    # --------------------------------------------------------
    # Non-zero return consumes pass, exactly one call, no retry
    # --------------------------------------------------------

    plan, preview, store, authorization = issued(
        "runner-nonzero"
    )

    nonzero = FakeProcessRunner(
        returncode=42,
        output="synthetic failure",
    )

    status, result = (
        runner_module.run_system_change_attempt(
            "matrix-ui+ocr",
            store,
            authorization,
            process_runner=nonzero,
        )
    )

    assert status == 10
    assert result["runner_status"] == "EXECUTION FAILED"
    assert result["authorization_consumed"] is True
    assert result["runner_returncode"] == 42
    assert len(nonzero.calls) == 1

    allowed, consumed = store.verify_and_consume(
        authorization,
        plan,
        preview,
    )

    assert allowed is False
    assert consumed["consumed"] is True

    ok("Non-zero execution consumes pass with no retry")


    # --------------------------------------------------------
    # Runner exception consumes pass
    # --------------------------------------------------------

    plan, preview, store, authorization = issued(
        "runner-exception"
    )

    exploding = FakeProcessRunner(
        exception=RuntimeError("boom")
    )

    status, result = (
        runner_module.run_system_change_attempt(
            "matrix-ui+ocr",
            store,
            authorization,
            process_runner=exploding,
        )
    )

    assert status == 11
    assert result["runner_status"] == "EXECUTION ERROR"
    assert result["authorization_consumed"] is True
    assert result["execution_performed"] is True
    assert len(exploding.calls) == 1

    allowed, consumed = store.verify_and_consume(
        authorization,
        plan,
        preview,
    )

    assert allowed is False
    assert consumed["consumed"] is True

    ok("Runner exception consumes pass and cannot retry")


    # --------------------------------------------------------
    # Unmarked injected process runner blocked before consume
    # --------------------------------------------------------

    plan, preview, store, authorization = issued(
        "runner-unmarked"
    )

    unmarked = UnmarkedRunner()

    status, result = (
        runner_module.run_system_change_attempt(
            "matrix-ui+ocr",
            store,
            authorization,
            process_runner=unmarked,
        )
    )

    assert status == 5
    assert result["authorization_consumed"] is False
    assert result["process_runner_invoked"] is False
    assert unmarked.calls == []

    allowed, consumed = store.verify_and_consume(
        authorization,
        plan,
        preview,
    )

    assert allowed is True
    assert consumed["consumed"] is True

    ok("Unmarked injected runner blocked before consume")


    # --------------------------------------------------------
    # Initial preflight failure leaves pass unused
    # --------------------------------------------------------

    plan, preview, store, authorization = issued(
        "runner-preflight-fail"
    )

    runner_module.verify_local_executor_prerequisites = (
        blocked_preflight
    )

    fake = FakeProcessRunner()

    status, result = (
        runner_module.run_system_change_attempt(
            "matrix-ui+ocr",
            store,
            authorization,
            process_runner=fake,
        )
    )

    assert status == 5
    assert result["authorization_consumed"] is False
    assert fake.calls == []

    allowed, consumed = store.verify_and_consume(
        authorization,
        plan,
        preview,
    )

    assert allowed is True
    assert consumed["consumed"] is True

    ok("Initial preflight failure leaves pass unused")


    # --------------------------------------------------------
    # Transaction drift permanently revokes before process
    # --------------------------------------------------------

    runner_module.verify_local_executor_prerequisites = (
        green_preflight
    )

    plan, preview, store, authorization = issued(
        "runner-transaction-drift"
    )

    def changed_preview(
        _feature_profile,
        current_plan,
    ):
        return 0, preview_for(
            current_plan,
            transaction_sha="d" * 64,
        )

    runner_module._build_preview_for_plan = changed_preview

    fake = FakeProcessRunner()

    status, result = (
        runner_module.run_system_change_attempt(
            "matrix-ui+ocr",
            store,
            authorization,
            process_runner=fake,
        )
    )

    assert status == 5
    assert result["authorization_consumed"] is False
    assert result["process_runner_invoked"] is False
    assert result["execution_performed"] is False
    assert fake.calls == []
    assert "revok" in result["reason"].lower()

    # The old exact transaction may return later, but the
    # previous authorization must remain permanently dead.
    allowed, revoked = store.verify_and_consume(
        authorization,
        plan,
        preview,
    )

    assert allowed is False
    assert revoked["consumed"] is False
    assert revoked["revoked"] is True
    assert (
        revoked["authorization_status"]
        == "REVOKED - TRANSACTION DRIFT"
    )

    ok(
        "Transaction drift permanently revokes "
        "authorization before production process"
    )


    # --------------------------------------------------------
    # Final preflight failure burns pass but never invokes process
    # --------------------------------------------------------

    plan, preview, store, authorization = issued(
        "runner-final-preflight"
    )

    def same_preview_again(
        _feature_profile,
        current_plan,
    ):
        return 0, preview_for(current_plan)

    runner_module._build_preview_for_plan = (
        same_preview_again
    )

    preflight_calls = {"count": 0}

    def final_fail_preflight(current_plan):
        preflight_calls["count"] += 1

        if preflight_calls["count"] == 1:
            return green_preflight(current_plan)

        return blocked_preflight(current_plan)

    runner_module.verify_local_executor_prerequisites = (
        final_fail_preflight
    )

    fake = FakeProcessRunner()

    status, result = (
        runner_module.run_system_change_attempt(
            "matrix-ui+ocr",
            store,
            authorization,
            process_runner=fake,
        )
    )

    assert status == 6
    assert result["runner_status"] == "BLOCKED AFTER CONSUME"
    assert result["authorization_consumed"] is True
    assert result["process_runner_invoked"] is False
    assert result["execution_performed"] is False
    assert fake.calls == []
    assert preflight_calls["count"] == 2

    allowed, consumed = store.verify_and_consume(
        authorization,
        plan,
        preview,
    )

    assert allowed is False
    assert consumed["consumed"] is True

    ok("Final preflight failure burns pass before process")


finally:
    runner_module.verify_local_executor_prerequisites = (
        original_preflight
    )
    runner_module._build_preview_for_plan = (
        original_preview_builder
    )


# ------------------------------------------------------------
# Product/source boundary checks
# ------------------------------------------------------------

source = (
    ROOT
    / "tools"
    / "memoria_package_system_change_runner.py"
).read_text(encoding="utf-8")

assert source.count("subprocess.run(") == 1
assert 'CANONICAL_APT_GET = "/usr/bin/apt-get"' in source
assert "shell=False" in source
assert 'cwd="/"' in source
assert "stdin=subprocess.DEVNULL" in source
assert "close_fds=True" in source
assert "dict(SAFE_CHILD_ENV)" in source
assert "verify_local_executor_prerequisites" in source
assert "verify_and_consume(" in source

for forbidden in (
    "shell=True",
    "Popen(",
    "os.system",
    "os.exec",
    "apt-get update",
    "systemctl",
    "argparse",
    "def main(",
    "write_text(",
    "write_bytes(",
):
    assert forbidden not in source, (
        f"Forbidden production runner marker: {forbidden}"
    )

ok("Production runner process boundary is narrowly scoped")


after = hashes()

assert before == after, (
    "Production runner regression modified protected files"
)

ok("Regression changed no protected product file")

print()
print(
    "MEMORIA Package System-Change Runner "
    "V0.1 Regression Test GREEN"
)
