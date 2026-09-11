#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path

import memoria_package_transaction_preview as preview

from memoria_package_install_plan import (
    build_installation_plan,
)


ROOT = Path(__file__).resolve().parents[1]

PROTECTED_FILES = [
    ROOT / "tools" / "memoria_package_executor.py",
    ROOT / "tools" / "memoria_package_install_plan.py",
    ROOT / "tools" / "memoria_package_system_change_authorization.py",
    ROOT / "tools" / "memoria_package_system_change_executor_harness.py",
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


def green_preflight(_plan):
    return {
        "verified": True,
        "executor_status": "LOCAL PREFLIGHT VERIFIED",
        "system_change_allowed": False,
        "execution_performed": False,
        "held_package_locks": [],
        "apt_get_path": "/usr/bin/apt-get",
        "reason": "Synthetic GREEN preflight.",
    }


class FakePreviewRunner:
    memoria_test_runner = True

    def __init__(
        self,
        *,
        returncode: int = 0,
        output: str = "",
        exception: Exception | None = None,
    ) -> None:
        self.returncode = returncode
        self.output = output
        self.exception = exception
        self.calls: list[
            tuple[list[str], dict[str, str]]
        ] = []

    def __call__(
        self,
        argv: list[str],
        env: dict[str, str],
    ) -> tuple[int, str]:
        self.calls.append(
            (list(argv), dict(env))
        )

        if self.exception is not None:
            raise self.exception

        return self.returncode, self.output


SAMPLE_GREEN = """Reading package lists...
Building dependency tree...
0 upgraded, 1 newly installed, 0 to remove and 70 not upgraded.
Inst tesseract-ocr-deu (1:4.1.0-2 Debian:13 [all])
Conf tesseract-ocr-deu (1:4.1.0-2 Debian:13 [all])
"""

SAMPLE_UPGRADE = """Reading package lists...
Building dependency tree...
3 upgraded, 0 newly installed, 0 to remove and 67 not upgraded.
Inst tigervnc-tools [1.15.0] (1.15.1 Debian:13 [amd64])
Inst tigervnc-standalone-server [1.15.0] (1.15.1 Debian:13 [amd64])
Inst tigervnc-common [1.15.0] (1.15.1 Debian:13 [amd64])
Conf tigervnc-tools (1.15.1 Debian:13 [amd64])
Conf tigervnc-standalone-server (1.15.1 Debian:13 [amd64])
Conf tigervnc-common (1.15.1 Debian:13 [amd64])
"""

SAMPLE_NO_SUMMARY = """Reading package lists...
Building dependency tree...
Inst tesseract-ocr-deu (1:4.1.0-2 Debian:13 [all])
Conf tesseract-ocr-deu (1:4.1.0-2 Debian:13 [all])
"""

SAMPLE_REMOVAL = """Reading package lists...
1 upgraded, 0 newly installed, 1 to remove and 0 not upgraded.
Inst example [1.0] (1.1 Debian:13 [amd64])
Remv kraki-filet-fisch [9.9]
Conf example (1.1 Debian:13 [amd64])
"""


before = hashes()

original_preflight = (
    preview.verify_local_executor_prerequisites
)

preview.verify_local_executor_prerequisites = (
    green_preflight
)

try:
    plan = build_installation_plan(
        "matrix-ui+ocr"
    )

    runner = FakePreviewRunner(
        output=SAMPLE_GREEN
    )

    status, result = preview.build_transaction_preview(
        "matrix-ui+ocr",
        runner=runner,
    )

    assert status == 0
    assert result["approvable"] is True
    assert result["preview_status"] == (
        "TRANSACTION PREVIEW VERIFIED"
    )
    assert result["execution_performed"] is False
    assert result["system_change_allowed"] is False
    assert result["simulation_performed"] is True
    assert result["runner_returncode"] == 0
    assert result["removal_lines"] == []
    assert result["operation_count"] == 2
    assert isinstance(
        result["transaction_sha256"],
        str,
    )

    expected_argv = [
        "/usr/bin/apt-get",
        "--simulate",
        *plan["command_argv"][1:],
    ]

    assert runner.calls == [
        (
            expected_argv,
            preview.SAFE_CHILD_ENV,
        )
    ]

    assert "LD_PRELOAD" not in preview.SAFE_CHILD_ENV
    assert "LD_LIBRARY_PATH" not in preview.SAFE_CHILD_ENV
    assert "APT_CONFIG" not in preview.SAFE_CHILD_ENV
    assert preview.SAFE_CHILD_ENV["LANG"] == "C"
    assert preview.SAFE_CHILD_ENV["LC_ALL"] == "C"

    second_runner = FakePreviewRunner(
        output=SAMPLE_GREEN
    )

    status2, result2 = (
        preview.build_transaction_preview(
            "matrix-ui+ocr",
            runner=second_runner,
        )
    )

    assert status2 == 0
    assert (
        result2["transaction_sha256"]
        == result["transaction_sha256"]
    )

    ok("Stable transaction fingerprint GREEN")

    upgrade_runner = FakePreviewRunner(
        output=SAMPLE_UPGRADE
    )

    status, blocked = (
        preview.build_transaction_preview(
            "matrix-ui+ocr",
            runner=upgrade_runner,
        )
    )

    assert status == 5
    assert blocked["approvable"] is False
    assert blocked["simulation_performed"] is True
    assert blocked["preview_status"] == (
        "BLOCKED - PACKAGE UPGRADE PRESENT"
    )

    ok("OCR package upgrade fails closed")

    no_summary_runner = FakePreviewRunner(
        output=SAMPLE_NO_SUMMARY
    )

    status, blocked = (
        preview.build_transaction_preview(
            "matrix-ui+ocr",
            runner=no_summary_runner,
        )
    )

    assert status == 5
    assert blocked["approvable"] is False
    assert blocked["preview_status"] == (
        "BLOCKED - APT SUMMARY UNVERIFIED"
    )

    ok("OCR package summary uncertainty fails closed")

    matrix_runner = FakePreviewRunner(
        output=SAMPLE_UPGRADE
    )

    status, matrix_result = (
        preview.build_transaction_preview(
            "matrix-ui",
            runner=matrix_runner,
        )
    )

    assert status == 0
    assert matrix_result["approvable"] is True
    assert matrix_result["preview_status"] == (
        "TRANSACTION PREVIEW VERIFIED"
    )

    ok("Matrix UI upgrade policy remains unchanged")

    removal_runner = FakePreviewRunner(
        output=SAMPLE_REMOVAL
    )

    status, blocked = (
        preview.build_transaction_preview(
            "matrix-ui+ocr",
            runner=removal_runner,
        )
    )

    assert status == 5
    assert blocked["approvable"] is False
    assert blocked["simulation_performed"] is True
    assert blocked["removal_lines"] == [
        "Remv kraki-filet-fisch [9.9]"
    ]
    assert blocked["transaction_sha256"]

    ok("Package removal fails closed")

    failed_runner = FakePreviewRunner(
        returncode=100,
        output="synthetic apt failure",
    )

    status, failed = (
        preview.build_transaction_preview(
            "matrix-ui+ocr",
            runner=failed_runner,
        )
    )

    assert status == 10
    assert failed["approvable"] is False
    assert failed["simulation_performed"] is True

    ok("Non-zero simulation fails closed")

    exception_runner = FakePreviewRunner(
        exception=RuntimeError(
            "synthetic simulation error"
        )
    )

    status, failed = (
        preview.build_transaction_preview(
            "matrix-ui+ocr",
            runner=exception_runner,
        )
    )

    assert status == 11
    assert failed["approvable"] is False
    assert failed["simulation_performed"] is False

    ok("Simulation exception fails closed")

    unmarked_calls = []

    def unmarked_runner(argv, env):
        unmarked_calls.append((argv, env))
        return 0, SAMPLE_GREEN

    status, blocked = (
        preview.build_transaction_preview(
            "matrix-ui+ocr",
            runner=unmarked_runner,
        )
    )

    assert status == 5
    assert blocked["simulation_performed"] is False
    assert unmarked_calls == []

    ok("Unmarked injected runner blocked")

    preview.verify_local_executor_prerequisites = (
        lambda _plan: {
            "verified": False,
            "executor_status": "BLOCKED",
            "system_change_allowed": False,
            "execution_performed": False,
            "held_package_locks": [
                "/var/lib/dpkg/lock-frontend"
            ],
            "apt_get_path": None,
            "reason": "Synthetic lock.",
        }
    )

    runner = FakePreviewRunner(
        output=SAMPLE_GREEN
    )

    status, blocked = (
        preview.build_transaction_preview(
            "matrix-ui+ocr",
            runner=runner,
        )
    )

    assert status == 5
    assert blocked["simulation_performed"] is False
    assert runner.calls == []

    ok("Preflight failure blocks before simulation")

finally:
    preview.verify_local_executor_prerequisites = (
        original_preflight
    )


source = (
    ROOT
    / "tools"
    / "memoria_package_transaction_preview.py"
).read_text(encoding="utf-8")

assert "subprocess.run(" in source
assert "shell=False" in source
assert 'cwd="/"' in source
assert "stdin=subprocess.DEVNULL" in source
assert "close_fds=True" in source

for forbidden in (
    "shell=True",
    "Popen(",
    "os.system",
    "os.exec",
    "apt-get update",
):
    assert forbidden not in source

ok("Preview process boundary is narrowly scoped")

after = hashes()

assert before == after, (
    "Transaction preview regression modified "
    "protected product files"
)

ok("Regression changed no protected product file")

print()
print(
    "MEMORIA Package Transaction Preview V0.1 "
    "Regression Test GREEN"
)
