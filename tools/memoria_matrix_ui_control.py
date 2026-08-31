#!/usr/bin/env python3
"""
MEMORIA Matrix UI Control V0.1


Small process controller for the optional graphical Matrix UI.

It can show status, start VNC/noVNC/Matrix UI, stop noVNC/Matrix UI,
and show logs. It does not change MEMORIA configuration, inspect private
content, sniff traffic, or upload anything.
"""

import argparse
import os
import signal
import subprocess
import time
from pathlib import Path

DEFAULT_VNC_GEOMETRY = os.environ.get("MEMORIA_VNC_GEOMETRY", "1920x1080")
DEFAULT_GEOMETRY = DEFAULT_VNC_GEOMETRY

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MATRIX_UI = PROJECT_ROOT / "tools" / "memoria_matrix_ui.py"
COCKPIT = PROJECT_ROOT / "tools" / "memoria_matrix_cockpit.py"
MATRIX_UI_LOG = Path("/tmp/memoria_matrix_ui.log")
NOVNC_LOG = Path("/tmp/novnc.log")

DEFAULT_DISPLAY = ":2"
DEFAULT_DEPTH = "24"
DEFAULT_VNC_PORT = 5902
DEFAULT_NOVNC_HOST = "0.0.0.0"
DEFAULT_NOVNC_PORT = 6080
DEFAULT_NOVNC_WEB = "/usr/share/novnc"


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


def run(command, timeout=20, env=None):
    try:
        result = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            env=env,
        )
        return result.returncode, result.stdout.strip()
    except FileNotFoundError:
        return 127, "command not found"
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout} seconds"
    except Exception as exc:
        return 1, str(exc)


def command_exists(name):
    code, _ = run(["bash", "-lc", f"command -v {name}"], timeout=5)
    return code == 0


def pgrep(pattern):
    code, output = run(["pgrep", "-af", pattern], timeout=5)
    if code != 0 or not output:
        return []
    rows = []
    for line_text in output.splitlines():
        if "memoria_matrix_ui_control.py" in line_text:
            continue
        rows.append(line_text)
    return rows


def port_listening(port):
    code, output = run(["ss", "-ltnp"], timeout=5)
    if code != 0:
        return False
    return f":{port}" in output


def x_socket_exists(display):
    number = display.replace(":", "").split(".")[0]
    return Path(f"/tmp/.X11-unix/X{number}").exists()


def show_status():
    print("MEMORIA MATRIX UI CONTROL V0.1")
    line()
    print("Process control only. No config changes. No private content.")
    line()

    section("Files")
    status("Matrix UI", str(MATRIX_UI.relative_to(PROJECT_ROOT)) if MATRIX_UI.exists() else "missing", ok=MATRIX_UI.exists())
    status("Terminal Cockpit", str(COCKPIT.relative_to(PROJECT_ROOT)) if COCKPIT.exists() else "missing", ok=COCKPIT.exists())

    section("Dependencies")
    vnc_ok = command_exists("vncserver")
    websockify_ok = command_exists("websockify")
    novnc_ok = Path(DEFAULT_NOVNC_WEB).exists()
    status("vncserver", "available" if vnc_ok else "not found", ok=vnc_ok)
    status("websockify", "available" if websockify_ok else "not found", ok=websockify_ok)
    status("noVNC web path", DEFAULT_NOVNC_WEB if novnc_ok else "not found", ok=novnc_ok)

    section("Processes")
    vnc_rows = pgrep("Xtigervnc|Xvnc|vncserver")
    ui_rows = pgrep("memoria_matrix_ui.py")
    novnc_rows = pgrep("websockify.*6080|novnc")
    status("VNC Process", "running" if vnc_rows else "not running", ok=True if vnc_rows else None)
    status("Matrix UI Process", "running" if ui_rows else "not running", ok=True if ui_rows else None)
    status("noVNC/websockify", "running" if novnc_rows else "not running", ok=True if novnc_rows else None)

    section("Display / Ports")
    status(f"DISPLAY {DEFAULT_DISPLAY} socket", "present" if x_socket_exists(DEFAULT_DISPLAY) else "not found", ok=True if x_socket_exists(DEFAULT_DISPLAY) else None)
    status(f"VNC port {DEFAULT_VNC_PORT}", "listening" if port_listening(DEFAULT_VNC_PORT) else "not listening", ok=True if port_listening(DEFAULT_VNC_PORT) else None)
    status(f"noVNC port {DEFAULT_NOVNC_PORT}", "listening" if port_listening(DEFAULT_NOVNC_PORT) else "not listening", ok=True if port_listening(DEFAULT_NOVNC_PORT) else None)

    section("Access")
    status("noVNC URL", f"http://SERVER-IP:{DEFAULT_NOVNC_PORT}/vnc.html", ok=None)
    section("Result")
    status("Matrix UI Control", "status completed", ok=True)


def start_vnc(display, geometry, depth):
    if x_socket_exists(display) or port_listening(DEFAULT_VNC_PORT):
        status("VNC", f"display {display} already appears to be running", ok=True)
        return True
    if not command_exists("vncserver"):
        status("VNC", "vncserver not found", ok=False)
        return False
    command = ["vncserver", display, "-geometry", geometry, "-depth", depth]
    code, output = run(command, timeout=30)
    if output:
        print(output)
    if code == 0:
        status("VNC", f"started on display {display}", ok=True)
        return True
    status("VNC", f"start failed with exit code {code}", ok=False)
    return False


def start_matrix_ui(display):
    if pgrep("memoria_matrix_ui.py"):
        status("Matrix UI", "already running", ok=True)
        return True
    if not MATRIX_UI.exists():
        status("Matrix UI", "tools/memoria_matrix_ui.py missing", ok=False)
        return False
    env = os.environ.copy()
    env["DISPLAY"] = display
    with MATRIX_UI_LOG.open("a", encoding="utf-8") as log:
        subprocess.Popen(
            ["python3", "tools/memoria_matrix_ui.py"],
            cwd=str(PROJECT_ROOT), stdout=log, stderr=subprocess.STDOUT,
            env=env, start_new_session=True,
        )
    time.sleep(1)
    if pgrep("memoria_matrix_ui.py"):
        status("Matrix UI", f"started on DISPLAY={display}", ok=True)
        status("Matrix UI Log", str(MATRIX_UI_LOG), ok=None)
        return True
    status("Matrix UI", "start requested but process not found", ok=False)
    status("Matrix UI Log", str(MATRIX_UI_LOG), ok=None)
    return False


def start_novnc(host, port, vnc_port):
    if port_listening(port):
        status("noVNC", f"already listening on port {port}", ok=True)
        return True
    if not command_exists("websockify"):
        status("noVNC", "websockify not found", ok=False)
        return False
    if not Path(DEFAULT_NOVNC_WEB).exists():
        status("noVNC", f"web path not found: {DEFAULT_NOVNC_WEB}", ok=False)
        return False
    command = ["websockify", f"{host}:{port}", f"localhost:{vnc_port}", f"--web={DEFAULT_NOVNC_WEB}"]
    with NOVNC_LOG.open("a", encoding="utf-8") as log:
        subprocess.Popen(command, cwd=str(PROJECT_ROOT), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    time.sleep(1)
    if port_listening(port):
        status("noVNC", f"listening on {host}:{port}", ok=True)
        status("noVNC URL", f"http://SERVER-IP:{port}/vnc.html", ok=None)
        status("noVNC Log", str(NOVNC_LOG), ok=None)
        return True
    status("noVNC", "start requested but port is not listening", ok=False)
    status("noVNC Log", str(NOVNC_LOG), ok=None)
    return False


def start_all(args):
    print("MEMORIA MATRIX UI CONTROL V0.1")
    line()
    print("Starting optional Matrix UI display path. No MEMORIA config changes. No private content.")
    line()
    section("Start VNC")
    vnc_ok = start_vnc(args.display, args.geometry, args.depth)
    section("Start Matrix UI")
    ui_ok = start_matrix_ui(args.display) if vnc_ok else False
    section("Start noVNC")
    novnc_ok = start_novnc(args.host, args.port, args.vnc_port) if vnc_ok else False
    section("Result")
    if vnc_ok and ui_ok and novnc_ok:
        status("Matrix UI Control", "start completed", ok=True)
        status("Open", f"http://SERVER-IP:{args.port}/vnc.html", ok=None)
        return 0
    status("Matrix UI Control", "start incomplete", ok=False)
    status("Hint", "run: python3 tools/memoria_matrix_ui_control.py logs", ok=None)
    return 1


def stop_matching(pattern, label):
    rows = pgrep(pattern)
    if not rows:
        status(label, "not running", ok=True)
        return True
    ok_all = True
    for row in rows:
        try:
            pid = int(row.split()[0])
            os.kill(pid, signal.SIGTERM)
            status(label, f"sent SIGTERM to PID {pid}", ok=True)
        except Exception as exc:
            status(label, str(exc), ok=False)
            ok_all = False
    return ok_all


def stop_all(args):
    print("MEMORIA MATRIX UI CONTROL V0.1")
    line()
    print("Stopping Matrix UI user-started processes. No config changes.")
    line()
    section("Stop Matrix UI")
    ui_ok = stop_matching("memoria_matrix_ui.py", "Matrix UI")
    section("Stop noVNC")
    novnc_ok = stop_matching("websockify.*6080|novnc", "noVNC/websockify")
    if args.stop_vnc:
        section("Stop VNC")
        code, output = run(["vncserver", "-kill", args.display], timeout=20)
        if output:
            print(output)
        vnc_ok = code == 0
        status("VNC", f"killed display {args.display}" if vnc_ok else f"kill returned exit code {code}", ok=vnc_ok)
    else:
        section("Stop VNC")
        status("VNC", "left running; use --stop-vnc to stop display", ok=None)
        vnc_ok = True
    section("Result")
    if ui_ok and novnc_ok and vnc_ok:
        status("Matrix UI Control", "stop completed", ok=True)
        return 0
    status("Matrix UI Control", "stop incomplete", ok=False)
    return 1


def show_logs(args):
    print("MEMORIA MATRIX UI CONTROL V0.1")
    line()
    print("Showing Matrix UI/noVNC logs.")
    line()
    for label, path in [("Matrix UI Log", MATRIX_UI_LOG), ("noVNC Log", NOVNC_LOG)]:
        section(label)
        if not path.exists():
            status(label, f"not found: {path}", ok=None)
            continue
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-args.lines:]
        if not lines:
            status(label, "empty", ok=None)
            continue
        for line_text in lines:
            print(line_text)
    section("Result")
    status("Logs", "completed", ok=True)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="MEMORIA Matrix UI Control V0.1")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status", help="show Matrix UI process/display status")
    start = sub.add_parser("start", help="start VNC, Matrix UI and noVNC")
    start.add_argument("--display", default=DEFAULT_DISPLAY)
    start.add_argument("--geometry", default=DEFAULT_GEOMETRY)
    start.add_argument("--depth", default=DEFAULT_DEPTH)
    start.add_argument("--host", default=DEFAULT_NOVNC_HOST)
    start.add_argument("--port", type=int, default=DEFAULT_NOVNC_PORT)
    start.add_argument("--vnc-port", type=int, default=DEFAULT_VNC_PORT)
    stop = sub.add_parser("stop", help="stop Matrix UI and noVNC")
    stop.add_argument("--display", default=DEFAULT_DISPLAY)
    stop.add_argument("--stop-vnc", action="store_true", help="also stop the VNC display")
    logs = sub.add_parser("logs", help="show recent logs")
    logs.add_argument("--lines", type=int, default=80)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        args.command = "status"
    if args.command == "status":
        show_status(); return 0
    if args.command == "start":
        return start_all(args)
    if args.command == "stop":
        return stop_all(args)
    if args.command == "logs":
        return show_logs(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
