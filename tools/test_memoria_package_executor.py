#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import tempfile
from copy import deepcopy
from pathlib import Path

import memoria_package_executor as executor

from memoria_package_approval_handoff import (
    build_approval_receipt,
)
from memoria_package_execution_gate import (
    build_execution_authorization,
)
from memoria_package_install_plan import (
    build_installation_plan,
)


ROOT = Path(__file__).resolve().parents[1]

PROTECTED_FILES = [
    ROOT / "tools" / "memoria_package_executor.py",
    ROOT / "tools" / "memoria_package_execution_gate.py",
    ROOT / "tools" / "memoria_package_approval_handoff.py",
    ROOT / "tools" / "memoria_package_install_plan.py",
    ROOT / "tools" / "memoria_package_profile.py",
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


def base_objects():
    plan = build_installation_plan("matrix-ui+ocr")
    receipt = build_approval_receipt(plan)

    authorization = build_execution_authorization(
        receipt,
        plan,
    )

    return plan, authorization


def expect_blocked(
    authorization,
    plan,
    label: str,
) -> None:
    result = executor.verify_executor_dry_run(
        authorization,
        plan,
    )

    assert result["verified"] is False
    assert result["executor_status"] == "BLOCKED"
    assert result["system_change_allowed"] is False
    assert result["execution_performed"] is False

    ok(label)


before = hashes()


# ------------------------------------------------------------
# Happy path
# ------------------------------------------------------------

plan, authorization = base_objects()

result = executor.verify_executor_dry_run(
    authorization,
    build_installation_plan("matrix-ui+ocr"),
)

assert result["verified"] is True
assert result["executor_status"] == "DRY RUN VERIFIED"
assert result["system_change_allowed"] is False
assert result["execution_performed"] is False

ok("Happy dry-run GREEN")


# ------------------------------------------------------------
# Feature-specific command shape
# ------------------------------------------------------------

for feature in (
    "minimal",
    "matrix-ui",
    "local-ocr",
    "matrix-ui+ocr",
):
    feature_plan = build_installation_plan(feature)

    assert executor.command_shape_is_safe(feature_plan)

    has_no_upgrade = (
        "--no-upgrade"
        in feature_plan["command_argv"]
    )

    if feature in ("local-ocr", "matrix-ui+ocr"):
        assert has_no_upgrade is True
    else:
        assert has_no_upgrade is False

ocr_plan = build_installation_plan("matrix-ui+ocr")
ocr_plan["command_argv"].remove("--no-upgrade")

assert executor.command_shape_is_safe(ocr_plan) is False

ok("Feature-specific no-upgrade command shape GREEN")


# ------------------------------------------------------------
# Shared local executor preflight
# ------------------------------------------------------------

preflight = executor.verify_local_executor_prerequisites(
    build_installation_plan("matrix-ui+ocr")
)

assert preflight["verified"] is True
assert (
    preflight["executor_status"]
    == "LOCAL PREFLIGHT VERIFIED"
)
assert preflight["execution_performed"] is False
assert preflight["system_change_allowed"] is False
assert preflight["held_package_locks"] == []
assert preflight["apt_get_path"] == "/usr/bin/apt-get"

ok("Shared local executor preflight GREEN")


# ------------------------------------------------------------
# Authorization tamper
# ------------------------------------------------------------

plan, authorization = base_objects()

tampered_auth = deepcopy(authorization)
tampered_auth["package_count"] = 999

expect_blocked(
    tampered_auth,
    plan,
    "Authorization tamper fails closed",
)


# ------------------------------------------------------------
# Plan tamper
# ------------------------------------------------------------

plan, authorization = base_objects()

tampered_plan = deepcopy(plan)
package = "kraki-polizei-fisch"

tampered_plan["packages"].append(package)
tampered_plan["package_count"] += 1
tampered_plan["command_argv"].append(package)

expect_blocked(
    authorization,
    tampered_plan,
    "Plan tamper fails closed",
)


# ------------------------------------------------------------
# Command shape tamper
# ------------------------------------------------------------

plan, authorization = base_objects()

tampered_plan = deepcopy(plan)
tampered_plan["command_argv"][2] = "--allow-unauthenticated"

expect_blocked(
    authorization,
    tampered_plan,
    "Command shape tamper fails closed",
)


# ------------------------------------------------------------
# Platform mismatch
# ------------------------------------------------------------

plan, authorization = base_objects()

tampered_plan = deepcopy(plan)
tampered_plan["platform_profile"] = "kraki-os"

expect_blocked(
    authorization,
    tampered_plan,
    "Platform mismatch fails closed",
)


# ------------------------------------------------------------
# Package manager mismatch
# ------------------------------------------------------------

plan, authorization = base_objects()

tampered_plan = deepcopy(plan)
tampered_plan["package_manager"] = "kraki-pkg"

expect_blocked(
    authorization,
    tampered_plan,
    "Package manager mismatch fails closed",
)


# ------------------------------------------------------------
# Support level mismatch
# ------------------------------------------------------------

plan, authorization = base_objects()

tampered_plan = deepcopy(plan)
tampered_plan["platform_support"] = "UNKNOWN / UNSUPPORTED"

# Authorization hash must correspond to this plan first,
# otherwise we'd only test the earlier authorization check.
receipt = build_approval_receipt(tampered_plan)
tampered_auth = build_execution_authorization(
    receipt,
    tampered_plan,
)

expect_blocked(
    tampered_auth,
    tampered_plan,
    "Unsupported platform level fails closed",
)


# ------------------------------------------------------------
# Unexpected execution mode
# ------------------------------------------------------------

plan, authorization = base_objects()

tampered_plan = deepcopy(plan)
tampered_plan["execution_mode"] = "KRAKI EXECUTE NOW"

receipt = build_approval_receipt(tampered_plan)
tampered_auth = build_execution_authorization(
    receipt,
    tampered_plan,
)

expect_blocked(
    tampered_auth,
    tampered_plan,
    "Unexpected execution mode fails closed",
)


# ------------------------------------------------------------
# Non-root simulation
# ------------------------------------------------------------

plan, authorization = base_objects()

original_geteuid = executor.os.geteuid

try:
    executor.os.geteuid = lambda: 1000

    expect_blocked(
        authorization,
        plan,
        "Non-root executor fails closed",
    )
finally:
    executor.os.geteuid = original_geteuid


# ------------------------------------------------------------
# Missing apt-get simulation
# ------------------------------------------------------------

plan, authorization = base_objects()

original_apt_get = executor.CANONICAL_APT_GET

try:
    executor.CANONICAL_APT_GET = Path(
        "/definitely/missing/memoria-apt-get"
    )

    expect_blocked(
        authorization,
        plan,
        "Missing canonical apt-get fails closed",
    )
finally:
    executor.CANONICAL_APT_GET = original_apt_get


# ------------------------------------------------------------
# Canonical apt-get trust policy
# ------------------------------------------------------------

plan, authorization = base_objects()

with tempfile.TemporaryDirectory() as tmpdir:
    fake_apt = Path(tmpdir) / "apt-get"
    fake_apt.write_text(
        "#!/bin/sh\nexit 0\n",
        encoding="utf-8",
    )
    fake_apt.chmod(0o777)

    original_apt_get = executor.CANONICAL_APT_GET

    try:
        executor.CANONICAL_APT_GET = fake_apt

        expect_blocked(
            authorization,
            plan,
            "World-writable apt-get fails closed",
        )
    finally:
        executor.CANONICAL_APT_GET = original_apt_get

ok("Canonical apt-get permission policy GREEN")


plan, authorization = base_objects()

with tempfile.TemporaryDirectory() as tmpdir:
    target = Path(tmpdir) / "real-apt-get"
    link = Path(tmpdir) / "apt-get"

    target.write_text(
        "#!/bin/sh\nexit 0\n",
        encoding="utf-8",
    )
    target.chmod(0o755)
    link.symlink_to(target)

    original_apt_get = executor.CANONICAL_APT_GET

    try:
        executor.CANONICAL_APT_GET = link

        expect_blocked(
            authorization,
            plan,
            "Symlink apt-get fails closed",
        )
    finally:
        executor.CANONICAL_APT_GET = original_apt_get

ok("Canonical apt-get symlink policy GREEN")


# ------------------------------------------------------------
# Zero-padded /proc/locks parser normalization
# ------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmpdir:
    fixture = Path(tmpdir) / "proc-locks"

    fixture.write_text(
        (
            "1: POSIX  ADVISORY  WRITE 1234 "
            "00:08:12345 0 EOF\n"
            "2: POSIX  ADVISORY  READ 5678 "
            "0a:0F:98765 0 EOF\n"
        ),
        encoding="utf-8",
    )

    original_path = executor.Path

    def fixture_path(value):
        if str(value) == "/proc/locks":
            return fixture
        return original_path(value)

    try:
        executor.Path = fixture_path

        locked = executor._locked_inode_keys()

        assert (0, 8, 12345) in locked
        assert (10, 15, 98765) in locked

        assert "00:08:12345" not in locked
        assert "0a:0f:98765" not in locked

        ok("Zero-padded /proc/locks parser normalization GREEN")
    finally:
        executor.Path = original_path


# ------------------------------------------------------------
# Held package lock simulation
# ------------------------------------------------------------

plan, authorization = base_objects()

original_locks = executor.held_package_locks

try:
    executor.held_package_locks = lambda: [
        "/var/lib/dpkg/lock-frontend"
    ]

    result = executor.verify_executor_dry_run(
        authorization,
        plan,
    )

    assert result["verified"] is False
    assert result["executor_status"] == "BLOCKED"
    assert result["execution_performed"] is False
    assert result["held_package_locks"] == [
        "/var/lib/dpkg/lock-frontend"
    ]

    ok("Held package lock fails closed")
finally:
    executor.held_package_locks = original_locks


# ------------------------------------------------------------
# Product files unchanged
# ------------------------------------------------------------

after = hashes()

assert before == after, (
    "Package Executor regression modified protected product files"
)

ok("Regression changed no protected product file")


# ------------------------------------------------------------
# Static execution safety
# ------------------------------------------------------------

source = (
    ROOT
    / "tools"
    / "memoria_package_executor.py"
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
):
    assert forbidden not in source, (
        f"Forbidden executor marker: {forbidden}"
    )

ok("Dry-run executor contains no process execution logic")


print()
print(
    "MEMORIA Package Executor Dry-Run Guard "
    "V0.1 Regression Test GREEN"
)
