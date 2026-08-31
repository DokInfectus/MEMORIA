#!/usr/bin/env python3
"""
MEMORIA Matrix UI Doctor V0.1

Read-only preflight doctor for the graphical Matrix UI.

It does not change configuration.
It does not start network services.
It does not inspect private content.
It explains whether Matrix UI can run directly, through VNC/noVNC,
or whether the terminal cockpit should be used.
"""

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

MATRIX_UI = PROJECT_ROOT / "tools" / "memoria_matrix_ui.py"
TERMINAL_COCKPIT = PROJECT_ROOT / "tools" / "memoria_matrix_cockpit.py"
SYSTEM_SNAPSHOT = PROJECT_ROOT / "tools" / "memoria_system_snapshot.py"


def line():
    print("-" * 60)


def section(title):
    print()
    print(f"## {title}")
    line()


def status(label, message, ok=None):
    if ok is True:
        prefix = "OK  "
    elif ok is False:
        prefix = "FAIL"
    else:
        prefix = "INFO"

    print(f"{prefix} {label}: {message}")


def command_exists(name):
    return shutil.which(name) is not None


def run_short(command, timeout=5):
    try:
        result = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip()
    except FileNotFoundError:
        return 127, "command not found"
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout} seconds"
    except Exception as exc:
        return 1, str(exc)


def check_python_tkinter():
    section("Python GUI Dependency")

    spec = importlib.util.find_spec("tkinter")

    if spec is None:
        status("tkinter", "not available", ok=False)
        status("Recommendation", "install python3-tk if Matrix UI is wanted", ok=None)
        return False

    status("tkinter", "available", ok=True)
    return True


def check_display():
    section("Display Environment")

    display = os.environ.get("DISPLAY")
    wayland = os.environ.get("WAYLAND_DISPLAY")

    if display:
        status("DISPLAY", display, ok=True)
    else:
        status("DISPLAY", "not set", ok=None)

    if wayland:
        status("WAYLAND_DISPLAY", wayland, ok=True)
    else:
        status("WAYLAND_DISPLAY", "not set", ok=None)

    if display or wayland:
        status("Graphical Display", "available for this shell", ok=True)
        return True

    status("Graphical Display", "not available for this shell", ok=False)
    status("Fallback", "use Terminal Cockpit or explicit VNC/noVNC display", ok=None)
    return False


def check_tools():
    section("MEMORIA UI Tools")

    found_all = True

    for label, path in [
        ("Matrix UI", MATRIX_UI),
        ("Terminal Cockpit", TERMINAL_COCKPIT),
        ("System Snapshot", SYSTEM_SNAPSHOT),
    ]:
        if path.exists():
            status(label, str(path.relative_to(PROJECT_ROOT)), ok=True)
        else:
            status(label, f"missing: {path.relative_to(PROJECT_ROOT)}", ok=False)
            found_all = False

    return found_all


def check_vnc_novnc():
    section("VNC / noVNC Path")

    vncserver = command_exists("vncserver")
    xtigervnc = command_exists("Xtigervnc") or command_exists("xtigervnc")
    websockify = command_exists("websockify")
    novnc_path = Path("/usr/share/novnc")

    status("vncserver", "available" if vncserver else "not found", ok=vncserver)
    status("Xtigervnc", "available" if xtigervnc else "not found", ok=xtigervnc)
    status("websockify", "available" if websockify else "not found", ok=websockify)
    status("noVNC web path", str(novnc_path) if novnc_path.exists() else "not found", ok=novnc_path.exists())

    if vncserver and websockify and novnc_path.exists():
        status("VNC/noVNC", "server-side display path is available", ok=True)
        return True

    status("VNC/noVNC", "not fully available", ok=False)
    status(
        "Recommendation",
        "install tigervnc-standalone-server tigervnc-tools novnc websockify if server-side GUI is wanted",
        ok=None,
    )
    return False


def check_running_display():
    section("Running Display / Ports")

    x2_socket = Path("/tmp/.X11-unix/X2")

    if x2_socket.exists():
        status("DISPLAY :2", "X socket exists", ok=True)
    else:
        status("DISPLAY :2", "X socket not found", ok=None)

    code, output = run_short(["ss", "-ltnp"], timeout=5)

    if code != 0:
        status("ss", output or f"exit code {code}", ok=None)
        return x2_socket.exists()

    has_5902 = ":5902" in output
    has_6080 = ":6080" in output

    status("VNC port 5902", "listening" if has_5902 else "not listening", ok=has_5902)
    status("noVNC port 6080", "listening" if has_6080 else "not listening", ok=has_6080)

    return has_5902 or has_6080 or x2_socket.exists()


def check_gpu():
    section("GPU Visibility")

    if not command_exists("nvidia-smi"):
        status("nvidia-smi", "not found", ok=None)
        return False

    code, output = run_short(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,temperature.gpu,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        timeout=5,
    )

    if code != 0:
        status("nvidia-smi", output or f"exit code {code}", ok=False)
        return False

    rows = [row.strip() for row in output.splitlines() if row.strip()]

    if not rows:
        status("GPU", "no rows returned", ok=None)
        return False

    for index, row in enumerate(rows, start=1):
        status(f"GPU {index}", row, ok=True)

    return True


def final_recommendation(has_tk, has_display, has_tools, has_vnc, has_running_display):
    section("Recommendation")

    if not has_tools:
        status("Matrix UI", "MEMORIA UI files are incomplete", ok=False)
        status("Next Step", "repair Matrix UI installation", ok=None)
        return 1

    if has_tk and has_display:
        status("Recommended Mode", "Matrix UI direct display", ok=True)
        status("Command", "python3 tools/memoria_matrix_ui.py", ok=None)
        return 0

    if has_tk and has_vnc:
        status("Recommended Mode", "Matrix UI through VNC/noVNC", ok=True)

        if has_running_display:
            status("Display State", "server-side display appears to be running", ok=True)
            status("Command", "DISPLAY=:2 python3 tools/memoria_matrix_ui.py", ok=None)
        else:
            status("Display State", "start VNC/noVNC first", ok=None)
            status("VNC", "vncserver :2 -geometry 1600x900 -depth 24", ok=None)
            status("noVNC", "websockify --web=/usr/share/novnc/ 0.0.0.0:6080 localhost:5902", ok=None)

        return 0

    status("Recommended Mode", "Terminal Cockpit", ok=True)
    status("Command", "python3 tools/memoria_matrix_cockpit.py", ok=None)

    if not has_tk:
        status("Why", "python tkinter is missing", ok=None)
    elif not has_display:
        status("Why", "no graphical display is available", ok=None)

    return 0


def main():
    print("MEMORIA MATRIX UI DOCTOR V0.1")
    line()
    print("Read-only Matrix UI preflight. No config changes. No private content.")
    line()

    has_tk = check_python_tkinter()
    has_display = check_display()
    has_tools = check_tools()
    has_vnc = check_vnc_novnc()
    has_running_display = check_running_display()
    check_gpu()

    result = final_recommendation(
        has_tk=has_tk,
        has_display=has_display,
        has_tools=has_tools,
        has_vnc=has_vnc,
        has_running_display=has_running_display,
    )

    section("Result")
    status("Matrix UI Doctor", "completed", ok=True)

    return result


if __name__ == "__main__":
    raise SystemExit(main())
