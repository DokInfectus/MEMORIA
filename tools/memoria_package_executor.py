#!/usr/bin/env python3
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from memoria_package_approval_handoff import plan_sha256


SCHEMA_VERSION = "memoria-package-executor-dry-run-v0.1"

EXECUTION_GATE_SCHEMA = "memoria-package-execution-gate-v0.1"

PACKAGE_LOCKS = (
    Path("/var/lib/dpkg/lock"),
    Path("/var/lib/dpkg/lock-frontend"),
    Path("/var/lib/apt/lists/lock"),
    Path("/var/cache/apt/archives/lock"),
)

CANONICAL_APT_GET = Path("/usr/bin/apt-get")


def authorization_matches_plan(
    authorization: dict[str, Any],
    plan: dict[str, Any],
) -> bool:
    if authorization.get("schema_version") != EXECUTION_GATE_SCHEMA:
        return False

    if authorization.get("authorized") is not True:
        return False

    if (
        authorization.get("authorization_status")
        != "AUTHORIZED FOR FUTURE EXECUTOR"
    ):
        return False

    if authorization.get("system_change_allowed") is not False:
        return False

    if authorization.get("installation_status") != "BLOCKED":
        return False

    if (
        authorization.get("feature_profile")
        != plan.get("feature_profile")
    ):
        return False

    if (
        authorization.get("platform_profile")
        != plan.get("platform_profile")
    ):
        return False

    if (
        authorization.get("package_manager")
        != plan.get("package_manager")
    ):
        return False

    if (
        authorization.get("package_count")
        != plan.get("package_count")
    ):
        return False

    return (
        authorization.get("plan_sha256")
        == plan_sha256(plan)
    )


def command_shape_is_safe(
    plan: dict[str, Any],
) -> bool:
    argv = list(plan.get("command_argv") or [])
    packages = list(plan.get("packages") or [])

    if not argv or not packages:
        return False

    expected = [
        "apt-get",
        "install",
        "--yes",
        "--no-install-recommends",
    ]

    if plan.get("feature_profile") in (
        "local-ocr",
        "matrix-ui+ocr",
    ):
        expected.append("--no-upgrade")

    expected.extend(packages)

    return argv == expected


def _locked_inode_keys() -> set[tuple[int, int, int]]:
    proc_locks = Path("/proc/locks")

    if not proc_locks.is_file():
        raise RuntimeError("/proc/locks unavailable")

    result: set[tuple[int, int, int]] = set()

    for line in proc_locks.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():
        fields = line.split()

        for field in fields:
            parts = field.split(":")

            if len(parts) != 3:
                continue

            major, minor, inode = parts

            try:
                key = (
                    int(major, 16),
                    int(minor, 16),
                    int(inode),
                )
            except ValueError:
                continue

            result.add(key)
            break

    return result


def held_package_locks() -> list[str]:
    locked = _locked_inode_keys()
    held: list[str] = []

    for path in PACKAGE_LOCKS:
        if not path.exists():
            continue

        stat = path.stat()

        key = (
            os.major(stat.st_dev),
            os.minor(stat.st_dev),
            stat.st_ino,
        )

        if key in locked:
            held.append(str(path))

    return held


def verify_apt_get_executable(
) -> tuple[bool, str | None, str | None]:
    """
    Verify the canonical Debian apt-get executable without PATH lookup.
    """

    path = CANONICAL_APT_GET

    try:
        if path.is_symlink():
            return (
                False,
                None,
                "Canonical apt-get path must not be a symlink.",
            )

        resolved = path.resolve(strict=True)
        metadata = path.stat()
    except OSError as exc:
        return (
            False,
            None,
            f"Canonical apt-get could not be verified: {exc}",
        )

    if resolved != path:
        return (
            False,
            None,
            "Canonical apt-get resolved to an unexpected path.",
        )

    if not stat.S_ISREG(metadata.st_mode):
        return (
            False,
            None,
            "Canonical apt-get is not a regular file.",
        )

    if metadata.st_uid != 0 or metadata.st_gid != 0:
        return (
            False,
            None,
            "Canonical apt-get is not owned by root:root.",
        )

    if metadata.st_mode & 0o022:
        return (
            False,
            None,
            "Canonical apt-get is group/world writable.",
        )

    if metadata.st_mode & (stat.S_ISUID | stat.S_ISGID):
        return (
            False,
            None,
            "Canonical apt-get has unexpected set-id bits.",
        )

    if not metadata.st_mode & stat.S_IXUSR:
        return (
            False,
            None,
            "Canonical apt-get is not executable by root.",
        )

    return True, str(path), None


def verify_local_executor_prerequisites(
    current_plan: dict[str, Any],
) -> dict[str, Any]:
    """Verify local prerequisites without consuming authorization."""

    result: dict[str, Any] = {
        "verified": False,
        "executor_status": "BLOCKED",
        "system_change_allowed": False,
        "execution_performed": False,
        "plan_sha256": plan_sha256(current_plan),
        "reason": None,
        "held_package_locks": [],
        "apt_get_path": None,
    }

    if current_plan.get("platform_profile") != "debian-13":
        result["reason"] = (
            "Executor supports only Debian 13."
        )
        return result

    if current_plan.get("package_manager") != "apt":
        result["reason"] = (
            "Debian 13 executor requires APT."
        )
        return result

    if current_plan.get("platform_support") != (
        "TESTED / OFFICIALLY SUPPORTED"
    ):
        result["reason"] = (
            "Platform support level is not eligible."
        )
        return result

    if current_plan.get("package_profile_available") is not True:
        result["reason"] = (
            "Package profile is unavailable."
        )
        return result

    if current_plan.get("execution_mode") != "DRY RUN ONLY":
        result["reason"] = (
            "Unexpected installation-plan execution mode."
        )
        return result

    if current_plan.get("system_change_allowed") is not False:
        result["reason"] = (
            "Installation plan unexpectedly allows system changes."
        )
        return result

    if current_plan.get("installation_status") != "BLOCKED":
        result["reason"] = (
            "Installation plan is not in expected BLOCKED state."
        )
        return result

    if not command_shape_is_safe(current_plan):
        result["reason"] = (
            "Installation command shape is not approved."
        )
        return result

    if os.geteuid() != 0:
        result["reason"] = (
            "Future package execution requires root."
        )
        return result

    apt_ok, apt_path, apt_reason = (
        verify_apt_get_executable()
    )

    if apt_ok is not True:
        result["reason"] = apt_reason
        return result

    result["apt_get_path"] = apt_path

    try:
        locks = held_package_locks()
    except (OSError, RuntimeError) as exc:
        result["reason"] = (
            "Package lock state could not be verified: "
            f"{exc}"
        )
        return result

    result["held_package_locks"] = locks

    if locks:
        result["reason"] = (
            "APT/DPKG package lock is currently held."
        )
        return result

    result["verified"] = True
    result["executor_status"] = "LOCAL PREFLIGHT VERIFIED"
    result["reason"] = (
        "Local executor prerequisites verified."
    )

    return result


def verify_executor_dry_run(
    authorization: dict[str, Any],
    current_plan: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "verified": False,
        "executor_status": "BLOCKED",
        "system_change_allowed": False,
        "execution_performed": False,
        "plan_sha256": plan_sha256(current_plan),
        "reason": None,
        "held_package_locks": [],
        "apt_get_path": None,
    }

    if not authorization_matches_plan(
        authorization,
        current_plan,
    ):
        result["reason"] = (
            "Execution authorization does not match "
            "the current installation plan."
        )
        return result

    preflight = verify_local_executor_prerequisites(
        current_plan
    )

    result["apt_get_path"] = preflight.get(
        "apt_get_path"
    )

    result["held_package_locks"] = list(
        preflight.get("held_package_locks") or []
    )

    if preflight.get("verified") is not True:
        result["reason"] = preflight.get("reason")
        return result

    result["verified"] = True
    result["executor_status"] = "DRY RUN VERIFIED"
    result["reason"] = (
        "Authorization, plan and local executor prerequisites "
        "verified. Execution remains disabled."
    )

    return result
