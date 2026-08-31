#!/usr/bin/env python3
from __future__ import annotations

import argparse
from typing import Any, Callable, Sequence

from memoria_package_install_orchestrator import (
    run_package_installation_orchestrator,
)
from memoria_package_profile import FEATURE_LABELS


SCHEMA_VERSION = "memoria-package-install-cli-v0.1"

OrchestratorRunner = Callable[
    [str],
    tuple[int, dict[str, Any]],
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the MEMORIA package installation orchestrator "
            "for one explicit feature profile."
        )
    )

    parser.add_argument(
        "--feature",
        required=True,
        choices=tuple(FEATURE_LABELS),
    )

    return parser


def print_result(
    status: int,
    result: dict[str, Any],
) -> None:
    print()
    print("MEMORIA PACKAGE INSTALL CLI V0.1")
    print("-" * 64)
    print(
        "Orchestrator Status: "
        f"{result.get('orchestrator_status', 'UNKNOWN')}"
    )
    print(f"Stage: {result.get('stage', 'unknown')}")
    print(
        "Execution Performed: "
        f"{'yes' if result.get('execution_performed') is True else 'no'}"
    )
    print(f"Exit Status: {status}")
    print(f"Reason: {result.get('reason')}")


def main(
    argv: Sequence[str] | None = None,
    *,
    orchestrator_runner: OrchestratorRunner = (
        run_package_installation_orchestrator
    ),
) -> int:
    args = build_parser().parse_args(argv)

    if (
        orchestrator_runner
        is not run_package_installation_orchestrator
        and getattr(
            orchestrator_runner,
            "memoria_test_runner",
            None,
        ) is not True
    ):
        print("PACKAGE INSTALL CLI: BLOCKED")
        print("Injected orchestrator runner is not approved.")
        return 5

    status, result = orchestrator_runner(
        args.feature,
    )

    if not isinstance(result, dict):
        print("PACKAGE INSTALL CLI: ERROR")
        print("Orchestrator returned invalid result.")
        return 11

    print_result(status, result)

    return status


if __name__ == "__main__":
    raise SystemExit(main())
