#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import stat
import sys
from pathlib import Path


BOOTSTRAP_VERIFIER = Path(
    "/usr/local/lib/memoria/"
    "memoria_release_runtime_integrity.py"
)

PYTHON = Path("/usr/bin/python3")

TOOLS = {
    "cockpit": "memoria_matrix_cockpit.py",
    "matrix-ui": "memoria_matrix_ui_control.py",
    "service": "memoria_service_manager.py",
}


class LauncherError(RuntimeError):
    pass


def usage() -> None:
    print("MEMORIA Runtime Launcher V0.1")
    print()
    print("Usage:")
    print("  memoria verify")
    print("  memoria cockpit")
    print("  memoria matrix-ui <arguments>")
    print("  memoria service <arguments>")


def load_bootstrap_verifier():
    if not BOOTSTRAP_VERIFIER.is_file():
        raise LauncherError(
            "canonical bootstrap verifier missing"
        )

    spec = importlib.util.spec_from_file_location(
        "memoria_bootstrap_runtime_integrity",
        BOOTSTRAP_VERIFIER,
    )

    if spec is None or spec.loader is None:
        raise LauncherError(
            "cannot load canonical bootstrap verifier"
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def verified_project_root(verifier):
    result = verifier.verify_installed_runtime()

    if not isinstance(result, dict):
        raise LauncherError(
            "runtime integrity returned invalid result"
        )

    if result.get("ok") is not True:
        raise LauncherError(
            "runtime integrity is not GREEN"
        )

    root_text = result.get("project_root")

    if not isinstance(root_text, str):
        raise LauncherError(
            "verified project_root missing"
        )

    root = Path(root_text)

    if (
        not root.is_absolute()
        or ".." in root.parts
    ):
        raise LauncherError(
            "verified project_root invalid"
        )

    return root, result


def checked_tool(
    project_root: Path,
    command: str,
) -> Path:
    name = TOOLS[command]
    tool = project_root / "tools" / name

    try:
        meta = tool.lstat()
    except OSError as exc:
        raise LauncherError(
            f"verified tool unavailable: {name}"
        ) from exc

    if not stat.S_ISREG(meta.st_mode):
        raise LauncherError(
            f"verified tool is not regular file: {name}"
        )

    return tool


def build_command(
    project_root: Path,
    argv: list[str],
) -> list[str]:
    if not argv:
        raise LauncherError(
            "launcher command required"
        )

    command = argv[0]

    if command not in TOOLS:
        raise LauncherError(
            f"unsupported launcher command: {command}"
        )

    if command == "cockpit" and len(argv) != 1:
        raise LauncherError(
            "cockpit accepts no launcher arguments"
        )

    if command in {
        "matrix-ui",
        "service",
    } and len(argv) < 2:
        raise LauncherError(
            f"{command} requires tool arguments"
        )

    tool = checked_tool(
        project_root,
        command,
    )

    return [
        str(PYTHON),
        str(tool),
        *argv[1:],
    ]


def dispatch(
    verifier,
    argv: list[str],
    executor,
) -> int:
    project_root, result = (
        verified_project_root(verifier)
    )

    if argv == ["verify"]:
        print("RUNTIME INTEGRITY: GREEN")
        print(
            "active_release: "
            f"{result.get('active_release')}"
        )
        print(
            "project_root: "
            f"{result.get('project_root')}"
        )
        return 0

    command = build_command(
        project_root,
        argv,
    )

    executor(command)

    return 0


def production_exec(command: list[str]) -> None:
    os.execv(
        command[0],
        command,
    )


def main() -> int:
    argv = sys.argv[1:]

    if not argv or argv[0] in {
        "-h",
        "--help",
        "help",
    }:
        usage()
        return 0 if argv else 2

    if argv[0] not in {
        "verify",
        "cockpit",
        "matrix-ui",
        "service",
    }:
        print("RUNTIME LAUNCHER: BLOCKED")
        print(
            "reason: unsupported launcher command"
        )
        return 23

    try:
        verifier = load_bootstrap_verifier()

        return dispatch(
            verifier,
            argv,
            production_exec,
        )

    except Exception as exc:
        print("RUNTIME LAUNCHER: BLOCKED")
        print(
            f"reason: {type(exc).__name__}: {exc}"
        )
        return 23


if __name__ == "__main__":
    raise SystemExit(main())
