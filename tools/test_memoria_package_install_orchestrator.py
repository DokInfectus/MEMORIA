#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path

import memoria_package_install_orchestrator as orchestrator
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

PRODUCT = (
    ROOT
    / "tools"
    / "memoria_package_install_orchestrator.py"
)

PROTECTED_FILES = [
    PRODUCT,
    ROOT / "tools" / "memoria_package_execution_gate.py",
    ROOT / "tools" / "memoria_package_execution_flow.py",
    ROOT / "tools" / "memoria_package_install_plan.py",
    ROOT / "tools" / "memoria_package_transaction_preview.py",
    ROOT / "tools" / "memoria_package_transaction_approval.py",
    ROOT / "tools" / "memoria_package_system_change_authorization.py",
    ROOT / "tools" / "memoria_package_system_change_runner.py",
    ROOT / "scripts" / "install.sh",
    ROOT / "Release_check.md",
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
            "Inst memoria-orchestrator-test-package (1.0)",
            "Conf memoria-orchestrator-test-package (1.0)",
        ],
        "summary_lines": [],
        "removal_lines": [],
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


def fake_flow(
    feature_profile,
    *,
    plan_builder,
):
    current_plan = plan_builder(feature_profile)
    return 0, flow_for(current_plan)


def fake_preview(
    feature_profile,
    *,
    plan_builder,
):
    current_plan = plan_builder(feature_profile)
    return 0, preview_for(current_plan)


def approve_exact(
    current_plan,
    transaction_preview,
):
    return (
        0,
        build_transaction_approval_receipt(
            current_plan,
            transaction_preview,
        ),
    )


class FakeProcessRunner:
    memoria_test_runner = True

    def __init__(
        self,
        returncode: int = 0,
        output: str = "synthetic apt output",
    ):
        self.returncode = returncode
        self.output = output
        self.calls = []

    def __call__(self, argv, env):
        self.calls.append(
            (list(argv), dict(env))
        )
        return self.returncode, self.output


before = hashes()

original_preflight = (
    runner_module.verify_local_executor_prerequisites
)
original_runner_preview = (
    runner_module._build_preview_for_plan
)

try:
    runner_module.verify_local_executor_prerequisites = (
        green_preflight
    )

    def same_runner_preview(
        _feature_profile,
        current_plan,
    ):
        return 0, preview_for(current_plan)

    runner_module._build_preview_for_plan = (
        same_runner_preview
    )

    # --------------------------------------------------------
    # Minimal: no package transaction, no process
    # --------------------------------------------------------

    calls = {
        "preview": 0,
        "approval": 0,
    }

    def minimal_flow(
        _feature_profile,
        *,
        plan_builder,
    ):
        return 0, {
            "schema_version": (
                "memoria-package-execution-flow-v0.1"
            ),
            "flow_status": "NOT REQUIRED",
            "system_change_allowed": False,
            "execution_performed": False,
            "executor_result": None,
        }

    def should_not_preview(*args, **kwargs):
        calls["preview"] += 1
        raise AssertionError(
            "Preview must not run for NOT REQUIRED."
        )

    def should_not_approve(*args, **kwargs):
        calls["approval"] += 1
        raise AssertionError(
            "Approval must not run for NOT REQUIRED."
        )

    fake = FakeProcessRunner()

    status, result = (
        orchestrator.run_package_installation_orchestrator(
            "minimal",
            flow_runner=minimal_flow,
            preview_builder=should_not_preview,
            approval_requester=should_not_approve,
            process_runner=fake,
        )
    )

    assert status == 0
    assert result["orchestrator_status"] == "NOT REQUIRED"
    assert result["execution_performed"] is False
    assert calls == {
        "preview": 0,
        "approval": 0,
    }
    assert fake.calls == []

    ok("Minimal NOT REQUIRED path GREEN")

    # --------------------------------------------------------
    # Transaction approval decline: no authorization/process
    # --------------------------------------------------------

    def decline_exact(
        _current_plan,
        _transaction_preview,
    ):
        return 1, None

    fake = FakeProcessRunner()

    status, result = (
        orchestrator.run_package_installation_orchestrator(
            "matrix-ui+ocr",
            flow_runner=fake_flow,
            preview_builder=fake_preview,
            approval_requester=decline_exact,
            process_runner=fake,
        )
    )

    assert status == 1
    assert result["transaction_approval_created"] is False
    assert result["authorization_issued"] is False
    assert result["execution_performed"] is False
    assert fake.calls == []

    ok("Transaction decline blocks before authorization")

    # --------------------------------------------------------
    # Happy full orchestration with real auth store
    # and marked FAKE process boundary
    # --------------------------------------------------------

    fake = FakeProcessRunner(
        returncode=0,
        output="ORCHESTRATOR TEST OUTPUT",
    )

    status, result = (
        orchestrator.run_package_installation_orchestrator(
            "matrix-ui+ocr",
            flow_runner=fake_flow,
            preview_builder=fake_preview,
            approval_requester=approve_exact,
            process_runner=fake,
        )
    )

    plan = build_installation_plan("matrix-ui+ocr")

    expected_argv = [
        "/usr/bin/apt-get",
        *plan["command_argv"][1:],
    ]

    assert status == 0
    assert (
        result["orchestrator_status"]
        == "EXECUTION COMPLETED"
    )
    assert result["transaction_approval_created"] is True
    assert result["authorization_issued"] is True
    assert result["execution_performed"] is True
    assert result["runner_result"]["runner_status"] == (
        "EXECUTION COMPLETED"
    )

    assert fake.calls == [
        (
            expected_argv,
            dict(SAFE_CHILD_ENV),
        )
    ]

    ok("Happy same-process orchestration GREEN")

    # --------------------------------------------------------
    # Drift between approval and production runner
    # permanently revokes before process
    # --------------------------------------------------------

    def changed_runner_preview(
        _feature_profile,
        current_plan,
    ):
        return 0, preview_for(
            current_plan,
            transaction_sha="d" * 64,
        )

    runner_module._build_preview_for_plan = (
        changed_runner_preview
    )

    fake = FakeProcessRunner()

    status, result = (
        orchestrator.run_package_installation_orchestrator(
            "matrix-ui+ocr",
            flow_runner=fake_flow,
            preview_builder=fake_preview,
            approval_requester=approve_exact,
            process_runner=fake,
        )
    )

    assert status == 5
    assert result["authorization_issued"] is True
    assert result["execution_performed"] is False
    assert result["runner_result"]["authorization_consumed"] is False
    assert "revok" in result["reason"].lower()
    assert fake.calls == []

    ok("Transaction drift revokes before process")

    # --------------------------------------------------------
    # Non-zero real-boundary model: exactly one attempt
    # --------------------------------------------------------

    runner_module._build_preview_for_plan = (
        same_runner_preview
    )

    fake = FakeProcessRunner(
        returncode=42,
        output="synthetic failure",
    )

    status, result = (
        orchestrator.run_package_installation_orchestrator(
            "matrix-ui+ocr",
            flow_runner=fake_flow,
            preview_builder=fake_preview,
            approval_requester=approve_exact,
            process_runner=fake,
        )
    )

    assert status == 10
    assert result["orchestrator_status"] == "EXECUTION FAILED"
    assert result["execution_performed"] is True
    assert len(fake.calls) == 1

    ok("Non-zero package attempt has no orchestrator retry")

finally:
    runner_module.verify_local_executor_prerequisites = (
        original_preflight
    )
    runner_module._build_preview_for_plan = (
        original_runner_preview
    )


# ------------------------------------------------------------
# Product/source boundary
# ------------------------------------------------------------

source = PRODUCT.read_text(encoding="utf-8")

for forbidden in (
    "import subprocess",
    "subprocess.run",
    "Popen(",
    "os.system",
    "os.exec",
    "shell=True",
    "apt-get install",
    "apt-get update",
    "systemctl",
    "write_text(",
    "write_bytes(",
    "def main(",
    "argparse",
):
    assert forbidden not in source, (
        f"Forbidden orchestrator marker: {forbidden}"
    )

assert "run_package_execution_flow" in source
assert "build_transaction_preview" in source
assert "request_transaction_approval" in source
assert "OneShotSystemChangeAuthorizationStore" in source
assert "run_system_change_attempt" in source
assert source.count("run_system_change_attempt(") == 2

ok("Orchestrator owns no process execution implementation")


after = hashes()

assert before == after, (
    "Orchestrator regression modified protected product files"
)

ok("Regression changed no protected product file")

print()
print(
    "MEMORIA Package Install Orchestrator "
    "V0.1 Regression Test GREEN"
)
