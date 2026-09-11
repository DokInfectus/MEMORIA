#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
from typing import Any, Callable

from memoria_package_approval_handoff import plan_sha256
from memoria_package_executor import (
    verify_local_executor_prerequisites,
)
from memoria_package_install_plan import (
    build_installation_plan,
)


SCHEMA_VERSION = "memoria-package-transaction-preview-v0.1"

SAFE_CHILD_ENV = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/root",
    "LANG": "C",
    "LC_ALL": "C",
    "DEBIAN_FRONTEND": "noninteractive",
}

PlanBuilder = Callable[[str], dict[str, Any]]
PreviewRunner = Callable[
    [list[str], dict[str, str]],
    tuple[int, str],
]


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "preview_status": "BLOCKED",
        "approvable": False,
        "system_change_allowed": False,
        "execution_performed": False,
        "simulation_performed": False,
        "plan_sha256": None,
        "transaction_sha256": None,
        "operation_lines": [],
        "operation_count": 0,
        "removal_lines": [],
        "summary_lines": [],
        "simulation_argv": [],
        "runner_returncode": None,
        "preflight_result": None,
        "reason": reason,
    }


def _default_preview_runner(
    argv: list[str],
    env: dict[str, str],
) -> tuple[int, str]:
    completed = subprocess.run(
        argv,
        shell=False,
        check=False,
        cwd="/",
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        close_fds=True,
    )

    return completed.returncode, completed.stdout


def _operation_lines(output: str) -> list[str]:
    prefixes = ("Inst ", "Remv ", "Conf ")

    return [
        line.strip()
        for line in output.splitlines()
        if line.startswith(prefixes)
    ]


def _summary_lines(output: str) -> list[str]:
    return [
        line.strip()
        for line in output.splitlines()
        if (
            " upgraded, " in line
            and " newly installed, " in line
            and " to remove and " in line
            and " not upgraded." in line
        )
        or line.startswith("Need to get ")
        or line.startswith("After this operation, ")
    ]


def _summary_upgrade_count(
    summary_lines: list[str],
) -> int | None:
    marker = " upgraded, "

    for line in summary_lines:
        if marker not in line:
            continue

        value = line.split(marker, 1)[0].strip()

        if not value.isdigit():
            return None

        return int(value)

    return None


def _transaction_sha256(
    current_plan: dict[str, Any],
    operations: list[str],
) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "plan_sha256": plan_sha256(current_plan),
        "operation_lines": operations,
    }

    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def build_transaction_preview(
    feature_profile: str,
    *,
    plan_builder: PlanBuilder = build_installation_plan,
    runner: PreviewRunner = _default_preview_runner,
) -> tuple[int, dict[str, Any]]:
    result = _blocked(
        "APT transaction preview has not run."
    )

    if (
        runner is not _default_preview_runner
        and getattr(
            runner,
            "memoria_test_runner",
            None,
        ) is not True
    ):
        result["reason"] = (
            "Injected preview runner is not an approved "
            "MEMORIA test runner."
        )
        return 5, result

    current_plan = plan_builder(feature_profile)
    result["plan_sha256"] = plan_sha256(current_plan)

    preflight = verify_local_executor_prerequisites(
        current_plan
    )
    result["preflight_result"] = preflight

    if preflight.get("verified") is not True:
        result["reason"] = (
            "Local executor preflight failed."
        )
        return 5, result

    apt_path = preflight.get("apt_get_path")

    if apt_path != "/usr/bin/apt-get":
        result["reason"] = (
            "Preflight did not return canonical apt-get path."
        )
        return 5, result

    planned_argv = list(
        current_plan.get("command_argv") or []
    )

    if (
        feature_profile in (
            "local-ocr",
            "matrix-ui+ocr",
        )
        and "--no-upgrade" not in planned_argv
    ):
        result["preview_status"] = (
            "BLOCKED - NO-UPGRADE POLICY MISSING"
        )
        result["reason"] = (
            "OCR package plan is missing required "
            "--no-upgrade policy."
        )
        return 5, result

    simulation_argv = [
        apt_path,
        "--simulate",
        *planned_argv[1:],
    ]

    result["simulation_argv"] = simulation_argv

    try:
        returncode, output = runner(
            simulation_argv,
            dict(SAFE_CHILD_ENV),
        )
    except Exception as exc:
        result["preview_status"] = "SIMULATION ERROR"
        result["reason"] = (
            "APT simulation runner raised "
            f"{type(exc).__name__}."
        )
        return 11, result

    result["simulation_performed"] = True

    if type(returncode) is not int or not isinstance(
        output,
        str,
    ):
        result["preview_status"] = "SIMULATION ERROR"
        result["reason"] = (
            "APT simulation runner returned invalid result."
        )
        return 11, result

    result["runner_returncode"] = returncode

    if returncode != 0:
        result["preview_status"] = "SIMULATION FAILED"
        result["reason"] = (
            "APT simulation returned non-zero status."
        )
        return 10, result

    operations = _operation_lines(output)
    removals = [
        line
        for line in operations
        if line.startswith("Remv ")
    ]

    summary_lines = _summary_lines(output)

    result["operation_lines"] = operations
    result["operation_count"] = len(operations)
    result["removal_lines"] = removals
    result["summary_lines"] = summary_lines
    result["transaction_sha256"] = (
        _transaction_sha256(
            current_plan,
            operations,
        )
    )

    if removals:
        result["preview_status"] = (
            "BLOCKED - PACKAGE REMOVAL PRESENT"
        )
        result["reason"] = (
            "Package removal is not approvable in V0.1."
        )
        return 5, result

    if feature_profile in (
        "local-ocr",
        "matrix-ui+ocr",
    ):
        upgrade_count = _summary_upgrade_count(
            summary_lines
        )

        if upgrade_count is None:
            result["preview_status"] = (
                "BLOCKED - APT SUMMARY UNVERIFIED"
            )
            result["reason"] = (
                "OCR no-upgrade policy requires a "
                "verified APT package summary."
            )
            return 5, result

        if upgrade_count != 0:
            result["preview_status"] = (
                "BLOCKED - PACKAGE UPGRADE PRESENT"
            )
            result["reason"] = (
                "Package upgrades are not approvable "
                "for OCR profiles."
            )
            return 5, result

    result["preview_status"] = (
        "TRANSACTION PREVIEW VERIFIED"
    )
    result["approvable"] = True
    result["reason"] = (
        "APT simulation completed without package removals."
    )

    return 0, result
