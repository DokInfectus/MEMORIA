#!/usr/bin/env python3

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from memoria_i18n import (
    current_language as memoria_current_language,
    is_no as memoria_is_no,
    is_yes as memoria_is_yes,
    text as memoria_text,
)

from memoria_storage_paths import (
    managed_path as memoria_managed_path,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT_TEXT = str(PROJECT_ROOT)

if PROJECT_ROOT_TEXT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_TEXT)

CONFIG_PATH = PROJECT_ROOT / "config" / "runtime.json"

BIG_ARCHIVE_IMPORT_DIR = memoria_managed_path(
    "imports",
    env_var="MEMORIA_IMPORT_DIR",
    fallback_rel="imports",
)

BIG_ARCHIVE_CHECKPOINT_DIR = (
    BIG_ARCHIVE_IMPORT_DIR
    / "big-archive-checkpoints"
)

# Compatibility with the earlier explicit import layout:
#   <dedicated-volume>/imports/big-archive-checkpoints
#
# This is a read-only lookup path. Nothing is moved or rewritten.
# Project-local fallback must not escape PROJECT_ROOT.
if (
    not BIG_ARCHIVE_IMPORT_DIR.is_relative_to(PROJECT_ROOT)
    and BIG_ARCHIVE_IMPORT_DIR.parent.name == "memoria"
):
    BIG_ARCHIVE_LEGACY_CHECKPOINT_DIR = (
        BIG_ARCHIVE_IMPORT_DIR.parent.parent
        / "imports"
        / "big-archive-checkpoints"
    )
else:
    BIG_ARCHIVE_LEGACY_CHECKPOINT_DIR = None

TOOLS = {
    "50": ("OpenWebUI Context Server Status", ["python3", "tools/memoria_service_manager.py", "status"]),
    "51": ("OpenWebUI Context Server Start", ["python3", "tools/memoria_service_manager.py", "start", "openwebui_context_server", "--force"]),
    "52": ("OpenWebUI Context Server Stop", ["python3", "tools/memoria_service_manager.py", "stop", "openwebui_context_server"]),
    "53": ("OpenWebUI Context Server Health", ["python3", "tools/memoria_service_manager.py", "health", "openwebui_context_server"]),
    "1": ("Runtime Smoke Test", ["python3", "tools/memoria_runtime_smoke_test.py"]),
    "2": ("Adapter Live Test", ["python3", "tools/memoria_adapter_live_test.py"]),
    "3": ("Prompt Engine Live Test", ["python3", "tools/memoria_prompt_engine_live_test.py"]),
    "6": ("System / Hardware Snapshot", ["python3", "tools/memoria_system_snapshot.py"]),
    "7": ("Matrix UI Doctor", ["python3", "tools/memoria_matrix_ui_doctor.py"]),
    "8": ("USB Patch Finder", ["python3", "tools/memoria_usb_patch_finder.py"]),
    "9": ("Matrix UI Control Status", ["python3", "tools/memoria_matrix_ui_control.py", "status"]),
    "10": ("Matrix UI Start", ["python3", "tools/memoria_matrix_ui_control.py", "start"]),
    "11": ("Matrix UI Stop", ["python3", "tools/memoria_matrix_ui_control.py", "stop", "--stop-vnc"]),
    "12": ("Matrix UI Logs", ["python3", "tools/memoria_matrix_ui_control.py", "logs"]),
    "13": ("LLM Model Selection", ["python3", "tools/memoria_model_selection.py"]),
    "14": ("Docker / Tunnel Visibility", ["python3", "tools/memoria_docker_visibility.py"]),
    "15": ("Memory Store List", ["python3", "tools/memoria_memory_store.py", "list"]),
    "47": ("Memory Overview / Speicherübersicht", ["python3", "tools/memoria_memory_overview.py"]),
    "54": ("Gedächtnisdatei importieren", ["python3", "tools/memoria_memory_file_import.py", "status"]),
    "59": ("Bilder/Dateien übernehmen", ["python3", "tools/memoria_attachment_store.py", "list"]),
    "61": ("Ausgewählte Bilder lesen / OCR", ["python3", "tools/memoria_local_ocr.py", "--help"]),
    "60": ("Attachment-/Bilder verwalten", ["python3", "tools/memoria_attachment_store.py", "list"]),
    "55": ("MEM zurück ins Review-Becken", ["python3", "tools/memoria_memory_store.py", "list"]),
    "16": ("Memory Store Search: Benutzer", ["python3", "tools/memoria_memory_store.py", "search", "Benutzer"]),
    "17": ("Memory Live Test", ["python3", "tools/memoria_memory_live_test.py"]),
    "18": ("Open WebUI Memory Live Test", ["python3", "tools/memoria_openwebui_memory_live_test.py"]),
    "19": ("Open WebUI Adapter Live Test", ["python3", "tools/memoria_openwebui_adapter_live_test.py"]),
    "58": ("Open WebUI Context Filter V0.2 Regression", ["python3", "tools/test_openwebui_context_filter_v02.py"]),
    "20": ("Erinnerungsvorschläge", ["python3", "tools/memoria_memory_candidate_store.py", "list"]),
    "24": ("Eigene wichtige Trigger anzeigen", ["python3", "-c", "from pathlib import Path; p=Path('config/rules/user/custom_important.txt'); print(p.read_text(encoding='utf-8') if p.exists() else 'INFO No custom_important.txt found')"]),
    "29": ("Automatische Speicherregeln anzeigen", ["python3", "tools/memoria_memory_auto.py", "policy"]),
    "31": ("Speicher prüfen", ["python3", "tools/memoria_storage_advisor.py", "scan"]),
    "32": ("Speicher prüfen + versteckte Mounts", ["python3", "tools/memoria_storage_advisor.py", "scan", "--show-hidden"]),
    "33": ("Runtime Mode anzeigen", ["python3", "tools/memoria_runtime_mode.py", "status"]),
    "37": ("Memory Storage Watchdog anzeigen", ["python3", "tools/memoria_memory_storage_watchdog.py", "status"]),
    "38": ("Memory Storage Watchdog Check", ["python3", "tools/memoria_memory_storage_watchdog.py", "check"]),
    "42": ("MEMORIA Service Manager Status", ["python3", "tools/memoria_service_manager.py", "status"]),
    "39": ("Import-Inbox Ledger Scan", ["python3", "tools/memoria_memory_source_ledger.py", "scan"]),
    "40": ("Import-Inbox Ledger Config anzeigen", ["python3", "-c", "from pathlib import Path; p=Path('config/memory_source_ledger.json'); print(p.read_text(encoding='utf-8') if p.exists() else 'INFO config/memory_source_ledger.json not found')"]),
}

NETWORK_MARKERS = [
    "http://",
    "https://",
    "urllib",
    "requests",
    "socket",
    "telemetry",
    "upload",
    "sync",
    "onedrive",
    "google drive",
    "dropbox",
]


def clear():
    # No terminal clear codes in beta cockpit.
    print()


def line():
    print("-" * 60)


def header():
    clear()
    print("MEMORIA MATRIX COCKPIT BETA V0.6")
    line()
    print("Safe admin cockpit. Explicit actions only. No private content.")
    line()


def matrix_intro_enabled():
    disabled = os.environ.get("MEMORIA_NO_ANIMATION", "").strip().lower()
    if disabled in {"1", "true", "yes", "on"}:
        return False

    term = os.environ.get("TERM", "").strip().lower()
    if term in {"", "dumb"}:
        return False

    return sys.stdin.isatty() and sys.stdout.isatty()


NAVIGATION_WIDTH = 78
NAVIGATION_HEIGHT = 24
CSI = chr(27) + "["
COLOR_OK = CSI + "32m"
COLOR_WARNING = CSI + "33m"
COLOR_ERROR = CSI + "31m"
COLOR_MENU = CSI + "36m"
COLOR_INFO = CSI + "90m"
COLOR_RESET = CSI + "0m"
NAVIGATION_SCREEN_ACTIVE = False


def terminal_colors_enabled():
    term = os.environ.get("TERM", "").strip().lower()
    return (
        sys.stdout.isatty()
        and term not in {"", "dumb"}
        and "NO_COLOR" not in os.environ
    )


def color_text(text, color):
    if not terminal_colors_enabled():
        return text
    return f"{color}{text}{COLOR_RESET}"


def terminal_columns():
    try:
        return os.get_terminal_size(sys.stdout.fileno()).columns
    except (OSError, ValueError):
        return NAVIGATION_WIDTH


def navigation_left():
    return max(1, (terminal_columns() - NAVIGATION_WIDTH) // 2 + 1)


def enter_navigation_screen():
    global NAVIGATION_SCREEN_ACTIVE

    if not matrix_intro_enabled() or NAVIGATION_SCREEN_ACTIVE:
        return

    print(CSI + "?1049h", end="", flush=True)
    NAVIGATION_SCREEN_ACTIVE = True


def leave_navigation_screen():
    global NAVIGATION_SCREEN_ACTIVE

    if not NAVIGATION_SCREEN_ACTIVE:
        return

    print(CSI + "?1049l", end="", flush=True)
    NAVIGATION_SCREEN_ACTIVE = False


def matrix_intro():
    if not matrix_intro_enabled():
        return

    enter_navigation_screen()
    width = NAVIGATION_WIDTH
    left = navigation_left()
    frames = [
        "     |",
        "    ||",
        "   |||",
        "  ||||",
        "|||||  MEMORIA",
        "  ||||  MEMORIA  ||||",
        "   |||  MEMORIA  |||",
        "    ||  MEMORIA  ||",
        "     |  MEMORIA  |",
        "+" + "-" * (width - 2) + "+",
    ]

    for frame in frames:
        print(
            CSI + f"1;{left}f" +
            CSI + "2K" +
            frame.center(width),
            end="",
            flush=True,
        )
        time.sleep(0.3)


LAST_EXECUTED_ACTION = None


def remember_last_action(label):
    global LAST_EXECUTED_ACTION
    LAST_EXECUTED_ACTION = str(label)


def last_action_status_entry():
    label = LAST_EXECUTED_ACTION or "Noch keine Aktion"
    return f"Zuletzt ausgeführt: {label}"


def navigation_entries_with_last_action(entries):
    prepared = list(entries)
    capacity = NAVIGATION_HEIGHT - 3

    # Eine Leerzeile für Select und eine für den Status reservieren.
    if len(prepared) > capacity - 2:
        return prepared

    padding = capacity - len(prepared) - 1
    return (
        prepared
        + [""] * padding
        + [last_action_status_entry()]
    )


def navigation_frame_lines(title, entries):
    inner_width = NAVIGATION_WIDTH - 2
    title_text = f" MEMORIA :: {title} "
    top_fill = inner_width - len(title_text)

    if top_fill < 2:
        title_text = " MEMORIA "
        top_fill = inner_width - len(title_text)

    left_fill = top_fill // 2
    right_fill = top_fill - left_fill
    lines = [
        "+" + "-" * left_fill + title_text + "-" * right_fill + "+",
        "|" + " " * inner_width + "|",
    ]

    for entry in entries:
        visible = str(entry)[:inner_width - 2]
        lines.append("| " + visible.ljust(inner_width - 2) + " |")

    while len(lines) < NAVIGATION_HEIGHT - 1:
        lines.append("|" + " " * inner_width + "|")

    lines.append("+" + "-" * inner_width + "+")
    return lines[:NAVIGATION_HEIGHT]


def color_navigation_line(line):
    if not terminal_colors_enabled():
        return line

    if len(line) < 2:
        return color_text(line, COLOR_MENU)

    if line.startswith("+") and line.endswith("+"):
        inner = line[1:-1]
        title_start = len(inner) - len(inner.lstrip("-"))
        title_end = len(inner.rstrip("-"))

        if title_start < title_end:
            return (
                color_text("+" + inner[:title_start], COLOR_OK)
                + color_text(
                    inner[title_start:title_end],
                    COLOR_MENU,
                )
                + color_text(
                    inner[title_end:] + "+",
                    COLOR_OK,
                )
            )

        return color_text(line, COLOR_OK)

    if line.startswith("|") and line.endswith("|"):
        return (
            color_text("|", COLOR_OK)
            + color_text(line[1:-1], COLOR_MENU)
            + color_text("|", COLOR_OK)
        )

    return color_text(line, COLOR_MENU)


def render_navigation_frame(title, entries):
    entries = navigation_entries_with_last_action(entries)
    lines = navigation_frame_lines(title, entries)

    if not matrix_intro_enabled():
        print("\n".join(color_navigation_line(line) for line in lines))
        return

    enter_navigation_screen()
    left = navigation_left()

    for row, frame_line in enumerate(lines, start=1):
        print(
            CSI + f"{row};{left}f" +
            CSI + "2K" +
            color_navigation_line(frame_line),
            end="",
        )

    print(
        CSI + f"{NAVIGATION_HEIGHT - 2};{left + 2}f",
        end="",
        flush=True,
    )


def read_navigation_choice():
    if not matrix_intro_enabled():
        return input("Select: ").strip().lower()

    left = navigation_left()
    row = NAVIGATION_HEIGHT - 2
    input_width = NAVIGATION_WIDTH - 4

    print(
        CSI + f"{row};{left + 2}f" +
        " " * input_width +
        CSI + f"{row};{left + 2}f",
        end="",
        flush=True,
    )
    return input("Select: ").strip().lower()


def status(label, message, ok=None):
    if ok is True:
        prefix, color = "OK  ", COLOR_OK
    elif ok is False:
        prefix, color = "FAIL", COLOR_ERROR
    else:
        prefix, color = "INFO", COLOR_INFO
    print(f"{color_text(prefix, color)} {label}: {message}")


def pause():
    prompt = "\nPress Enter to return to cockpit..."
    input(color_text(prompt, COLOR_WARNING))


def show_runtime_config():
    header()
    print("## Runtime Config")
    line()
    if not CONFIG_PATH.exists():
        status("runtime.json", "not found", ok=False)
        pause()
        return
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        status("runtime.json", str(e), ok=False)
        pause()
        return
    safe_keys = [
        "setup_mode",
        "adapter",
        "base_url",
        "model",
        "profile",
        "prompt_profile",
        "context_length",
        "max_tokens",
        "memory_token_budget",
        "history_token_budget",
        "reserved_output_tokens",
    ]
    for key in safe_keys:
        if key in data:
            status(key, str(data[key]), ok=True)
    pause()


def run_tool(title, command):
    header()
    print(f"## {title}")
    line()
    try:
        result = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        print(result.stdout)
        if result.returncode == 0:
            self_reporting_titles = {"Docker / Tunnel Visibility", "USB Patch Finder"}
            if title not in self_reporting_titles and "## Result" not in result.stdout:
                status(title, "completed", ok=True)
        else:
            status(title, f"exit code {result.returncode}", ok=False)

    except subprocess.TimeoutExpired:
        status(title, "timeout after 120 seconds", ok=False)
    except Exception as e:
        status(title, str(e), ok=False)
    pause()


def scan_network_markers():
    header()
    print("## Network / Sync Visibility Scan")
    line()
    print("This is a visibility scan only.")
    print("It does not inspect user traffic and does not capture packets.")
    line()
    hits = []
    for path in PROJECT_ROOT.rglob("*.py"):
        parts = set(path.parts)
        if "__pycache__" in parts or ".git" in parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        lowered = text.lower()
        for marker in NETWORK_MARKERS:
            if marker in lowered:
                hits.append((path.relative_to(PROJECT_ROOT), marker))
                break
    if not hits:
        status("Network Markers", "none found", ok=True)
    else:
        status("Network Markers", f"{len(hits)} file(s) contain network/sync markers", ok=None)
        for rel_path, marker in hits:
            print(f"INFO {rel_path}: marker '{marker}'")
    print()
    print("Allowed examples:")
    print("- local llama.cpp calls to 127.0.0.1 / localhost")
    print("- explicit user-requested install/update checks")
    print("- explicit diagnostics shown to the user")
    print()
    print("Not allowed:")
    print("- hidden telemetry")
    print("- private data uploads")
    print("- traffic sniffing")
    print("- background sync without user action")
    pause()


MENU_GROUPS = [
    ("1", "Core / Live Tests", ["1", "2", "3", "17", "18", "19"]),
    ("2", "Configuration / Model", ["4", "44", "45", "46"]),
    ("3", "Memory / Gedanken Speicherung", ["47", "62", "15", "48", "54", "59", "61", "60", "57", "41", "49", "56", "55", "39", "40"]),
    ("4", "System / Hardware", ["6", "31", "32", "37", "38"]),
    ("5", "Security / Visibility", ["5", "14"]),
    ("6", "Matrix UI Control", ["7", "9", "10", "11", "12"]),
    ("7", "Patch / USB Tools", ["8"]),
    ("8", "Runtime / Service Mode", ["33", "42", "50", "51", "52", "53", "43", "34", "35", "36"]),
]


RELEASE_BLOCKED_ACTIONS = frozenset(
    (
        "58",
    )
)


ACTION_LABELS = {
    "57": "Große Gedächtnisdatei / Big Archive",
    "55": "MEM zurück ins Review-Becken",
    "56": "Memory Trash / Papierkorb",
    "54": "Gedächtnisdatei importieren",
    "59": "Bilder/Dateien übernehmen",
    "61": "Ausgewählte Bilder lesen / OCR",
    "62": "Memory Token Usage",
    "60": "Attachment-/Bilder verwalten",
    "49": "MEM Lifecycle / Erinnerungen aktivieren-deaktivieren",
    "48": "Gedächtnisdateien prüfen",
    "47": "Memory Overview / Speicherübersicht",
    "4": "Show Runtime Config",
    "5": "Network / Sync Visibility Scan",
    "21": "Letzten Vorschlag anzeigen",
    "22": "Text analysieren",
    "23": "Text analysieren + Vorschlag erzeugen",
    "25": "Letzten Vorschlag freigeben",
    "26": "Letzten Vorschlag ablehnen",
    "27": "Letzten Vorschlag archivieren",
    "28": "Letzten freigegebenen Vorschlag speichern",
    "30": "Text automatisch nach User-Filtern speichern",
    "34": "NORMAL aktivieren",
    "35": "THINKING_MODE aktivieren",
    "36": "SERVICE_STOP aktivieren",
    "43": "Source Ledger Config setzen",
    "44": "Runtime Token Budgets setzen",
    "45": "Runtime Adapter Config setzen",
    "46": "Runtime Profile Config setzen",
}

# Legacy flat-menu label reference for migration/test visibility:
# print("1) Runtime Smoke Test")
# print("2) Adapter Live Test")
# print("3) Prompt Engine Live Test")
# print("4) Show Runtime Config")
# print("5) Network / Sync Visibility Scan")
# print("6) System / Hardware Snapshot")
# print("7) Matrix UI Doctor")
# print("8) USB Patch Finder")
# print("9) Matrix UI Control Status")
# print("10) Matrix UI Start")
# print("11) Matrix UI Stop")
# print("12) Matrix UI Logs")
# print("13) LLM Model Selection")



def run_command_inline(title, command, timeout=120):
    print()
    print(f"## {title}")
    line()
    try:
        result = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        print(result.stdout)
        if result.returncode == 0:
            status(title, "completed", ok=True)
        else:
            status(title, f"failed with exit code {result.returncode}", ok=False)
        return result.returncode
    except subprocess.TimeoutExpired:
        status(title, "timeout", ok=False)
        return 124


def action_label(action_key):
    if action_key == "41":
        return "User Filter / Filtermaschine"
    if action_key in TOOLS:
        return TOOLS[action_key][0]
    return ACTION_LABELS.get(action_key, f"Unknown action {action_key}")



def set_runtime_mode_from_cockpit(mode, reason, require_confirmation=False):
    header()
    print(f"## Runtime Mode: {mode}")
    line()

    if mode == "THINKING_MODE":
        print("THINKING_MODE erlaubt Retrieval aus vorhandenem freigegebenem Wissen.")
        print("Neue Candidates, Promotion und durable Writes werden blockiert.")
        print()

    if mode == "SERVICE_STOP":
        print("SERVICE_STOP pausiert MEMORIA-Verarbeitung per Runtime Mode.")
        print("Keine neuen Candidates, keine Promotion, keine durable Writes.")
        print("Hinweis: Dieser Cockpit-Schalter stoppt noch keine systemd/Docker-Services.")
        print()

    if require_confirmation:
        print(f"Sicherheitsbestätigung erforderlich. Tippe exakt: {mode}")
        typed = input("Bestätigung: ").strip()
        if typed != mode:
            status("Runtime Mode", "abgebrochen: Bestätigung passt nicht", ok=False)
            pause()
            return

    runtime_code = run_command_inline(
        f"Runtime Mode {mode}",
        ["python3", "tools/memoria_runtime_mode.py", "set", mode, "--reason", reason],
    )

    service_code = run_command_inline(
        f"Runtime Services apply {mode}",
        ["python3", "tools/memoria_service_manager.py", "apply-runtime", mode],
    )

    if runtime_code == 0 and service_code == 0:
        status("Runtime / Service", "mode and enabled services applied", ok=True)
    else:
        status("Runtime / Service", "mode or service application failed", ok=False)

    pause()


def run_source_ledger_config_command(title, command):
    header()
    print(f"## {title}")
    line()
    try:
        result = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        print(result.stdout)
        if result.returncode == 0:
            status(title, "completed", ok=True)
        else:
            status(title, f"exit code {result.returncode}", ok=False)
    except subprocess.TimeoutExpired:
        status(title, "timeout after 120 seconds", ok=False)
    except Exception as e:
        status(title, str(e), ok=False)
    pause()


def run_source_ledger_config_commands(title, commands):
    header()
    print(f"## {title}")
    line()
    ok = True

    for command in commands:
        print("$ " + " ".join(command))
        try:
            result = subprocess.run(
                command,
                cwd=str(PROJECT_ROOT),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=120,
            )
            print(result.stdout)
            if result.returncode != 0:
                ok = False
                status("Command", f"exit code {result.returncode}", ok=False)
                break
        except subprocess.TimeoutExpired:
            ok = False
            status("Command", "timeout after 120 seconds", ok=False)
            break
        except Exception as e:
            ok = False
            status("Command", str(e), ok=False)
            break

    status(title, "completed" if ok else "failed", ok=ok)
    pause()


def resolve_managed_import_inbox_for_cockpit():
    command = [
        sys.executable,
        "-c",
        (
            "import sys; "
            "sys.path.insert(0, 'tools'); "
            "from memoria_storage_paths import managed_path; "
            "p = managed_path('imports', env_var='MEMORIA_IMPORT_DIR', fallback_rel='imports') / 'inbox'; "
            "p.mkdir(parents=True, exist_ok=True); "
            "print(p)"
        ),
    ]

    result = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
    )

    if result.returncode != 0:
        header()
        print("## Managed Inbox ermitteln")
        line()
        print(result.stdout)
        status("Managed Inbox", "could not resolve managed import inbox", ok=False)
        pause()
        return None

    return result.stdout.strip()


def run_source_ledger_config_menu():
    while True:
        header()
        print("## Source Ledger Config setzen")
        line()
        print("Was soll geändert werden?")
        print()
        print("1) Watch aktivieren")
        print("2) Watch deaktivieren")
        print("3) Poll-Intervall setzen")
        print("4) Managed Inbox setzen")
        print("5) Config anzeigen")
        print("6) Service Status anzeigen")
        print("b) Back")
        line()
        print("Hinweis:")
        print("- Aktivieren bedeutet: darf bei NORMAL laufen.")
        print("- SERVICE_STOP stoppt den Watcher.")
        print("- Es werden keine Candidates und keine durable Memories geschrieben.")
        print("- Es wird nur die explizite Import-Inbox beobachtet.")
        line()

        choice = input("Select: ").strip().lower()

        if choice == "b":
            return

        if choice == "1":
            run_source_ledger_config_command(
                "Source Ledger Watch aktivieren",
                ["python3", "tools/memoria_memory_source_ledger.py", "config", "set", "--enabled", "true"],
            )
            continue

        if choice == "2":
            run_source_ledger_config_commands(
                "Source Ledger Watch deaktivieren",
                [
                    ["python3", "tools/memoria_memory_source_ledger.py", "config", "set", "--enabled", "false"],
                    ["python3", "tools/memoria_service_manager.py", "stop", "source_ledger_watch"],
                ],
            )
            continue

        if choice == "3":
            header()
            print("## Poll-Intervall setzen")
            line()
            print("Minimum: 10 Sekunden")
            print("Empfohlen: 60 Sekunden")
            print()
            value = input("Neues Intervall in Sekunden: ").strip()

            if not value.isdigit():
                status("Poll-Intervall", "bitte eine Zahl eingeben", ok=False)
                pause()
                continue

            run_source_ledger_config_command(
                "Source Ledger Poll-Intervall setzen",
                ["python3", "tools/memoria_memory_source_ledger.py", "config", "set", "--interval", value],
            )
            continue

        if choice == "4":
            inbox = resolve_managed_import_inbox_for_cockpit()
            if not inbox:
                continue

            run_source_ledger_config_command(
                "Source Ledger Managed Inbox setzen",
                ["python3", "tools/memoria_memory_source_ledger.py", "config", "set", "--inbox", inbox],
            )
            continue

        if choice == "5":
            run_source_ledger_config_command(
                "Source Ledger Config anzeigen",
                ["python3", "tools/memoria_memory_source_ledger.py", "config", "show"],
            )
            continue

        if choice == "6":
            run_source_ledger_config_command(
                "MEMORIA Service Manager Status",
                ["python3", "tools/memoria_service_manager.py", "status"],
            )
            continue

        print("Unknown selection.")
        pause()




def run_runtime_config_command(title, command):
    header()
    print(f"## {title}")
    line()
    try:
        result = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        print(result.stdout)
        if result.returncode == 0:
            status(title, "completed", ok=True)
        else:
            status(title, f"exit code {result.returncode}", ok=False)
    except subprocess.TimeoutExpired:
        status(title, "timeout after 120 seconds", ok=False)
    except Exception as e:
        status(title, str(e), ok=False)
    pause()



def read_runtime_config_for_cockpit():
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def runtime_budget_summary_text(config):
    context = int(config.get("context_length", 0) or 0)
    planned = (
        int(config.get("max_tokens", 0) or 0)
        + int(config.get("memory_token_budget", 0) or 0)
        + int(config.get("history_token_budget", 0) or 0)
        + int(config.get("reserved_output_tokens", 0) or 0)
    )
    return planned, context - planned



def run_runtime_token_budget_menu():
    fields = {
        "2": ("context_length", "--context-length", "Context Length"),
        "3": ("max_tokens", "--max-tokens", "Max Output Tokens"),
        "4": ("memory_token_budget", "--memory-token-budget", "Memory Token Budget"),
        "5": ("history_token_budget", "--history-token-budget", "History Token Budget"),
        "6": ("reserved_output_tokens", "--reserved-output-tokens", "Reserved Output Tokens"),
    }

    while True:
        config = read_runtime_config_for_cockpit()
        planned, remaining = runtime_budget_summary_text(config)

        header()
        print("## Runtime Token Budgets setzen")
        line()
        print(f"Aktuell context_length: {config.get('context_length', 'unknown')}")
        print(f"Aktuell max_tokens: {config.get('max_tokens', 'unknown')}")
        print(f"Aktuell memory_token_budget: {config.get('memory_token_budget', 'unknown')}")
        print(f"Aktuell history_token_budget: {config.get('history_token_budget', 'unknown')}")
        print(f"Aktuell reserved_output_tokens: {config.get('reserved_output_tokens', 'unknown')}")
        print(f"Geplante Budget-Summe: {planned}")
        print(f"Rest nach Budget: {remaining}")
        line()
        print("1) Runtime Config anzeigen")
        print("2) Context Length setzen")
        print("3) Max Output Tokens setzen")
        print("4) Memory Token Budget setzen")
        print("5) History Token Budget setzen")
        print("6) Reserved Output Tokens setzen")
        print("b) Back")
        line()
        print("Hinweis:")
        print("- Werte werden in config/runtime.json geschrieben.")
        print("- Der Editor prüft, dass Token-Budgets nicht context_length überschreiten.")
        print("- Adapter-Auswahl kommt später als eigener Häppchen-Fish.")
        line()

        choice = input("Select: ").strip().lower()

        if choice == "b":
            return

        if choice == "1":
            run_runtime_config_command(
                "Runtime Config anzeigen",
                ["python3", "tools/memoria_runtime_config_editor.py", "show"],
            )
            continue

        if choice in fields:
            _key, flag, label = fields[choice]
            header()
            print(f"## {label} setzen")
            line()
            config = read_runtime_config_for_cockpit()
            old_value = config.get(_key, "unknown")
            print(f"Alter Wert: {old_value}")
            value = input("Neuer Wert (Enter = abbrechen): ").strip()

            if not value:
                status(label, "keine Änderung", ok=None)
                pause()
                continue

            if not value.isdigit():
                status(label, "bitte eine ganze Zahl eingeben", ok=False)
                pause()
                continue

            run_runtime_config_command(
                f"{label} setzen",
                ["python3", "tools/memoria_runtime_config_editor.py", "set", flag, value],
            )
            continue

        print("Unknown selection.")
        pause()




def run_cockpit_interactive_command(title, command):
    header()
    print(f"## {title}")
    line()
    print("$ " + " ".join(command))
    print()
    try:
        result = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode == 0:
            status(title, "completed", ok=True)
        else:
            status(title, f"exit code {result.returncode}", ok=False)
    except Exception as e:
        status(title, str(e), ok=False)
    pause()


def run_runtime_adapter_config_menu():
    adapter_choices = {
        "2": ("LlamaCppAdapter", "llama.cpp direct, default http://127.0.0.1:3000"),
        "3": ("OpenWebUIAdapter", "Open WebUI, default http://127.0.0.1:8080, API key separate"),
        "4": ("OllamaAdapter", "Ollama, default http://127.0.0.1:11434"),
        "5": ("MockAdapter", "Test adapter, no real backend"),
    }

    while True:
        config = read_runtime_config_for_cockpit()

        header()
        print("## Runtime Adapter Config setzen")
        line()
        print(f"Aktuell setup_mode: {config.get('setup_mode', 'unknown')}")
        print(f"Aktuell adapter: {config.get('adapter', 'unknown')}")
        print(f"Aktuell base_url: {config.get('base_url', 'unknown')}")
        print(f"Aktuell model: {config.get('model', 'unknown')}")
        print(f"Aktuell prompt_profile: {config.get('prompt_profile', 'unknown')}")
        line()
        print("1) Adapter Config anzeigen")
        print("2) LlamaCppAdapter setzen")
        print("3) OpenWebUIAdapter setzen")
        print("4) OllamaAdapter setzen")
        print("5) MockAdapter setzen")
        print("6) Base URL setzen")
        print("7) Model setzen")
        print("8) Open WebUI API Key Status")
        print("9) Open WebUI API Key Setup")
        print("b) Back")
        line()
        print("Hinweis:")
        print("- Adapter-Wechsel schreibt nur technische Runtime Config.")
        print("- Keine API Keys in runtime.json.")
        print("- Open WebUI API Key wird nur über das Key-Setup gespeichert.")
        print("- Es wird keine Verbindung getestet und kein Backend gestartet.")
        print("- Prompt Profile kommt später als eigener Häppchen-Fish.")
        line()

        choice = input("Select: ").strip().lower()

        if choice == "b":
            return

        if choice == "1":
            run_runtime_config_command(
                "Runtime Adapter Config anzeigen",
                ["python3", "tools/memoria_runtime_adapter_config.py", "show"],
            )
            continue

        if choice in adapter_choices:
            adapter_name, _description = adapter_choices[choice]
            run_runtime_config_command(
                f"{adapter_name} setzen",
                ["python3", "tools/memoria_runtime_adapter_config.py", "set", "--adapter", adapter_name],
            )
            continue

        if choice == "6":
            old_value = config.get("base_url", "")
            header()
            print("## Base URL setzen")
            line()
            print(f"Alter Wert: {old_value}")
            print("Beispiele:")
            print("- llama.cpp:   http://127.0.0.1:3000")
            print("- Open WebUI:  http://127.0.0.1:8080")
            print("- Ollama:      http://127.0.0.1:11434")
            print()
            value = input("Neue Base URL (Enter = abbrechen): ").strip()

            if not value:
                status("Base URL", "keine Änderung", ok=None)
                pause()
                continue

            run_runtime_config_command(
                "Base URL setzen",
                ["python3", "tools/memoria_runtime_adapter_config.py", "set", "--base-url", value],
            )
            continue

        if choice == "7":
            old_value = config.get("model", "")
            header()
            print("## Model setzen")
            line()
            print(f"Alter Wert: {old_value}")
            print("Hinweis: Keine API Keys oder Secrets als Modellname eingeben.")
            print()
            value = input("Neuer Model-Name (Enter = abbrechen): ").strip()

            if not value:
                status("Model", "keine Änderung", ok=None)
                pause()
                continue

            run_runtime_config_command(
                "Model setzen",
                ["python3", "tools/memoria_runtime_adapter_config.py", "set", "--model", value],
            )
            continue

        if choice == "8":
            run_runtime_config_command(
                "Open WebUI API Key Status",
                ["python3", "tools/memoria_openwebui_key_setup.py", "status"],
            )
            continue

        if choice == "9":
            run_cockpit_interactive_command(
                "Open WebUI API Key Setup",
                ["python3", "tools/memoria_openwebui_key_setup.py", "set"],
            )
            continue

        print("Unknown selection.")
        pause()




def run_runtime_profile_config_menu():
    prompt_profiles = {
        "2": "auto",
        "3": "gemma",
        "4": "llama",
        "5": "mistral",
        "6": "qwen",
        "7": "deepseek",
        "8": "phi",
        "9": "chatml",
        "10": "alpaca",
        "11": "generic",
        "12": "custom",
    }

    config_profiles = {
        "14": "balanced",
        "15": "fast-low-context",
        "16": "memory-heavy",
        "17": "low-vram",
        "18": "custom",
    }

    while True:
        config = read_runtime_config_for_cockpit()

        header()
        print("## Runtime Profile Config setzen")
        line()
        print(f"Aktuell profile: {config.get('profile', 'unknown')}")
        print(f"Aktuell prompt_profile: {config.get('prompt_profile', 'unknown')}")
        print(f"Aktuell model: {config.get('model', 'unknown')}")
        print(f"Aktuell adapter: {config.get('adapter', 'unknown')}")
        line()
        print("1) Runtime Profile Config anzeigen")
        print()
        print("Prompt Profile setzen:")
        print("2) auto")
        print("3) gemma")
        print("4) llama")
        print("5) mistral")
        print("6) qwen")
        print("7) deepseek")
        print("8) phi")
        print("9) chatml")
        print("10) alpaca")
        print("11) generic")
        print("12) custom")
        print()
        print("Configuration Profile setzen:")
        print("14) balanced")
        print("15) fast-low-context")
        print("16) memory-heavy")
        print("17) low-vram")
        print("18) custom")
        print("19) Configuration Profile + Token-Budgets anwenden")
        print("b) Back")
        line()
        print("Hinweis:")
        print("- Prompt Profile beeinflusst Prompt-/Modellformat.")
        print("- Configuration Profile ist Hardware-/Budget-Profil.")
        print("- Token-Budgets aus Profil werden nur bei Option 19 angewendet.")
        print("- Adapter-Auswahl bleibt im Adapter-Menü.")
        line()

        choice = input("Select: ").strip().lower()

        if choice == "b":
            return

        if choice == "1":
            run_runtime_config_command(
                "Runtime Profile Config anzeigen",
                ["python3", "tools/memoria_runtime_profile_config.py", "show"],
            )
            continue

        if choice in prompt_profiles:
            profile = prompt_profiles[choice]
            run_runtime_config_command(
                f"Prompt Profile {profile} setzen",
                ["python3", "tools/memoria_runtime_profile_config.py", "set-prompt", profile],
            )
            continue

        if choice in config_profiles:
            profile = config_profiles[choice]
            run_runtime_config_command(
                f"Configuration Profile {profile} setzen",
                ["python3", "tools/memoria_runtime_profile_config.py", "set-profile", profile],
            )
            continue

        if choice == "19":
            header()
            print("## Configuration Profile + Token-Budgets anwenden")
            line()
            print("Achtung: Diese Option überschreibt context_length/max_tokens/memory/history/reserved nach Profil.")
            print()
            print("1) balanced")
            print("2) fast-low-context")
            print("3) memory-heavy")
            print("4) low-vram")
            print("5) custom")
            print("b) Back")
            line()

            sub = input("Profil wählen: ").strip().lower()
            mapping = {
                "1": "balanced",
                "2": "fast-low-context",
                "3": "memory-heavy",
                "4": "low-vram",
                "5": "custom",
            }

            if sub == "b":
                continue

            if sub not in mapping:
                status("Profile Apply", "unknown selection", ok=False)
                pause()
                continue

            profile = mapping[sub]
            confirm = input(f"Type APPLY to apply token budgets from {profile}: ").strip()

            if confirm != "APPLY":
                status("Profile Apply", "not changed", ok=None)
                pause()
                continue

            run_runtime_config_command(
                f"Configuration Profile {profile} mit Token-Budgets anwenden",
                ["python3", "tools/memoria_runtime_profile_config.py", "set-profile", profile, "--apply-token-budgets"],
            )
            continue

        print("Unknown selection.")
        pause()





def cockpit_input(prompt: str) -> str:
    """Read one clean UTF-8 CLI value without crashing the cockpit.

    A malformed byte sequence can occur through terminal/noVNC paste.
    The damaged line is discarded and the user is asked again.
    """
    while True:
        try:
            value = input(prompt)
        except UnicodeDecodeError:
            # Process-local recovery only. No system or locale config changes.
            try:
                reconfigure = getattr(sys.stdin, "reconfigure", None)

                if callable(reconfigure):
                    reconfigure(errors="replace")
            except (OSError, ValueError):
                pass

            status(
                "CLI Eingabe",
                "ungültige UTF-8-Eingabe verworfen; bitte erneut eingeben",
                ok=False,
            )
            continue

        # After recovery, Python may replace a broken byte with U+FFFD.
        # Do not silently accept such a damaged path or menu selection.
        if "\ufffd" in value:
            status(
                "CLI Eingabe",
                "beschädigtes Zeichen erkannt; Eingabe wurde verworfen",
                ok=False,
            )
            continue

        return value


def run_big_archive_json_command(command):
    """Run one Big Archive Core command and parse one JSON object."""
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    output = result.stdout.strip()

    if result.returncode != 0:
        return None, (
            output
            or f"Core Tool exited with code {result.returncode}"
        )

    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        return None, f"invalid Big Archive JSON: {exc}"

    if not isinstance(payload, dict):
        return None, "Big Archive JSON root is not an object"

    return payload, None


def big_archive_checkpoint_dirs():
    """Return the exact managed and compatible legacy checkpoint paths."""
    directories = [BIG_ARCHIVE_CHECKPOINT_DIR]

    legacy = BIG_ARCHIVE_LEGACY_CHECKPOINT_DIR

    if (
        legacy is not None
        and legacy != BIG_ARCHIVE_CHECKPOINT_DIR
    ):
        directories.append(legacy)

    return directories


def load_ready_big_archives():
    """Inspect renderer archives in exact approved checkpoint paths."""
    items = []
    errors = []
    discovered = {}

    for directory in big_archive_checkpoint_dirs():
        if not directory.is_dir():
            continue

        try:
            candidates = directory.glob(
                "*-archive-v*.json"
            )

            for archive_path in candidates:
                try:
                    resolved = archive_path.resolve()
                    modified = resolved.stat().st_mtime
                except OSError as exc:
                    errors.append({
                        "file": archive_path.name,
                        "error": str(exc),
                    })
                    continue

                discovered[str(resolved)] = (
                    resolved,
                    modified,
                )

        except OSError as exc:
            errors.append({
                "file": str(directory),
                "error": str(exc),
            })

    paths = [
        item[0]
        for item in sorted(
            discovered.values(),
            key=lambda entry: entry[1],
            reverse=True,
        )
    ]

    seen_archive_hashes = set()

    for archive_path in paths[:20]:
        payload, error = run_big_archive_json_command(
            [
                sys.executable,
                "tools/memoria_big_archive_candidate.py",
                "inspect",
                "--archive",
                str(archive_path),
                "--json",
            ]
        )

        if error or payload is None:
            errors.append({
                "file": archive_path.name,
                "error": error or "unknown inspect error",
            })
            continue

        if payload.get("schema_version") != (
            "big-archive-candidate-inspect-v0.1"
        ):
            errors.append({
                "file": archive_path.name,
                "error": "unexpected inspect schema",
            })
            continue

        archive = payload.get("archive")
        source = payload.get("source")
        policy = payload.get("policy")

        archive_sha256 = (
            archive.get("sha256")
            if isinstance(archive, dict)
            else None
        )

        if (
            archive_sha256
            and archive_sha256 in seen_archive_hashes
        ):
            continue

        if archive_sha256:
            seen_archive_hashes.add(archive_sha256)

        if not isinstance(archive, dict):
            continue

        if not isinstance(source, dict):
            continue

        if not isinstance(policy, dict):
            continue

        if policy.get("candidate_written") is not False:
            continue

        if policy.get("durable_memory_written") is not False:
            continue

        candidate = payload.get("candidate")
        status_name = "ready"

        if isinstance(candidate, dict):
            if candidate.get("promoted_to"):
                status_name = "promoted"
            else:
                status_name = "candidate"

        items.append({
            "archive_file": str(archive_path),
            "archive_sha256": archive.get("sha256"),
            "title": archive.get("title"),
            "section_count": archive.get("section_count"),
            "readable_text_chars": (
                archive.get("readable_text_chars")
            ),
            "source_file": source.get("file"),
            "source_name": source.get("name"),
            "source_sha256": source.get("sha256"),
            "source_size_bytes": source.get("size_bytes"),
            "source_char_count": source.get("char_count"),
            "technical_chunks": source.get(
                "technical_chunks"
            ),
            "source_section_count": source.get(
                "source_section_count"
            ),
            "status": status_name,
            "candidate": candidate,
        })

    return {
        "schema_version": "big-archive-ready-list-v0.1",
        "count": len(items),
        "items": items,
        "errors": errors,
    }



def run_big_archive_core_action(command):
    """Execute one existing memory Core action.

    Successful technical output stays hidden. Complete diagnostic output
    remains visible when a Core Tool fails.
    """
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    output = result.stdout.strip()

    if result.returncode != 0 and output:
        print(output)

    return result.returncode, output


def run_big_archive_guided_import():
    """Import one completed renderer archive through one user decision."""
    language = memoria_current_language()

    def tr(key, **values):
        return memoria_text(
            key,
            language=language,
            **values,
        )

    def formatted_number(value):
        try:
            result = f"{int(value):,}"
        except (TypeError, ValueError):
            return "?"

        if language == "de":
            return result.replace(",", ".")

        return result

    def ask_yes_no():
        while True:
            answer = cockpit_input(
                tr("big_archive.confirm_store")
            ).strip()

            if memoria_is_yes(
                answer,
                language=language,
            ):
                return True

            if memoria_is_no(
                answer,
                language=language,
            ):
                return False

            print(tr("common.answer_yes_no"))

    ready = load_ready_big_archives()
    items = ready.get("items")

    if not isinstance(items, list) or not items:
        print()
        print(tr("big_archive.none_ready"))
        pause()
        return

    print()
    print(f"## {tr('big_archive.import_title')}")
    print("-" * 60)
    print(
        tr(
            "big_archive.ready_found",
            count=len(items),
        )
    )
    print()

    for index, item in enumerate(items, start=1):
        status_name = str(
            item.get("status") or "ready"
        )
        status_text = tr(
            f"big_archive.status_{status_name}"
        )

        print(
            f"{index}) "
            f"{item.get('title') or item.get('source_name')}"
        )
        print(
            "   "
            + tr(
                "big_archive.source",
                name=item.get("source_name") or "-",
            )
        )
        print(
            "   "
            + tr(
                "big_archive.size_bytes",
                count=formatted_number(
                    item.get("source_size_bytes")
                ),
            )
        )
        print(
            "   "
            + tr(
                "big_archive.source_chars",
                count=formatted_number(
                    item.get("source_char_count")
                ),
            )
        )
        print(
            "   "
            + tr(
                "big_archive.technical_chunks",
                count=formatted_number(
                    item.get("technical_chunks")
                ),
            )
        )
        print(
            "   "
            + tr(
                "big_archive.source_sections",
                count=formatted_number(
                    item.get("source_section_count")
                ),
            )
        )
        print(
            "   "
            + tr(
                "big_archive.archive_sections",
                count=formatted_number(
                    item.get("section_count")
                ),
            )
        )
        print(
            "   "
            + tr(
                "big_archive.readable_chars",
                count=formatted_number(
                    item.get("readable_text_chars")
                ),
            )
        )
        print(
            "   "
            + tr(
                "big_archive.status",
                status=status_text,
            )
        )
        print()

    while True:
        raw_choice = cockpit_input(
            tr("big_archive.choose")
        ).strip()

        if raw_choice == "0":
            return

        try:
            selected_index = int(raw_choice)
        except ValueError:
            print(tr("big_archive.invalid_number"))
            continue

        if 1 <= selected_index <= len(items):
            break

        print(tr("big_archive.invalid_number"))

    selected = items[selected_index - 1]

    if selected.get("status") == "promoted":
        print()
        print(tr("big_archive.already_promoted"))
        pause()
        return

    print()
    print(
        tr(
            "big_archive.source",
            name=selected.get("source_name") or "-",
        )
    )
    print(
        tr(
            "big_archive.source_sections",
            count=formatted_number(
                selected.get("source_section_count")
            ),
        )
    )
    print(
        tr(
            "big_archive.archive_sections",
            count=formatted_number(
                selected.get("section_count")
            ),
        )
    )
    print(tr("big_archive.result_one"))
    print(tr("big_archive.source_retained"))
    print()

    prepared, error = run_big_archive_json_command(
        [
            sys.executable,
            "tools/memoria_big_archive_candidate.py",
            "prepare",
            "--archive",
            str(selected.get("archive_file") or ""),
            "--json",
        ]
    )

    if error or not isinstance(prepared, dict):
        print(
            tr(
                "big_archive.prepare_failed",
                error=error or "invalid payload",
            )
        )
        pause()
        return

    if prepared.get("schema_version") != (
        "big-archive-candidate-prepare-v0.1"
    ):
        print(tr("big_archive.invalid_prepare"))
        pause()
        return

    candidate = prepared.get("candidate")
    created = prepared.get("created_this_invocation")
    policy = prepared.get("policy")

    if (
        not isinstance(candidate, dict)
        or not isinstance(created, bool)
        or not isinstance(policy, dict)
        or policy.get(
            "exactly_one_linked_candidate"
        ) is not True
    ):
        print(tr("big_archive.invalid_prepare"))
        pause()
        return

    candidate_id = str(
        candidate.get("id") or ""
    )

    if not candidate_id.startswith("CAND-"):
        print(tr("big_archive.invalid_prepare"))
        pause()
        return

    if candidate.get("promoted_to"):
        print(tr("big_archive.already_promoted"))
        pause()
        return

    if not ask_yes_no():
        if created:
            code, _output = run_big_archive_core_action(
                [
                    sys.executable,
                    "tools/memoria_memory_candidate_store.py",
                    "delete",
                    candidate_id,
                    "--confirm",
                    candidate_id[-5:],
                ]
            )

            if code == 0:
                print(tr("big_archive.cancel_removed"))
            else:
                print(tr("big_archive.cleanup_failed"))
        else:
            print(tr("big_archive.cancel_preserved"))

        pause()
        return

    if candidate.get("state") != "user-approved":
        code, _output = run_big_archive_core_action(
            [
                sys.executable,
                "tools/memoria_memory_candidate_store.py",
                "approve",
                candidate_id,
            ]
        )

        if code != 0:
            print(tr("big_archive.approve_failed"))
            pause()
            return

    code, _output = run_big_archive_core_action(
        [
            sys.executable,
            "tools/memoria_memory_promote.py",
            "promote",
            candidate_id,
        ]
    )

    if code != 0:
        print(tr("big_archive.promote_failed"))
        print(
            tr(
                "big_archive.approved_not_promoted"
            )
        )
        pause()
        return

    verified, verify_error = run_big_archive_json_command(
        [
            sys.executable,
            "tools/memoria_big_archive_candidate.py",
            "inspect",
            "--archive",
            str(selected.get("archive_file") or ""),
            "--json",
        ]
    )

    verified_candidate = (
        verified.get("candidate")
        if isinstance(verified, dict)
        else None
    )

    memory_id = (
        verified_candidate.get("promoted_to")
        if isinstance(verified_candidate, dict)
        else None
    )

    if (
        verify_error
        or not isinstance(verified, dict)
        or verified.get("linked_candidate_count") != 1
        or not isinstance(memory_id, str)
        or not memory_id.startswith("MEM-")
    ):
        print(tr("big_archive.postcheck_failed"))
        pause()
        return

    print()
    print(
        tr(
            "big_archive.saved",
            memory_id=memory_id,
        )
    )
    print(tr("big_archive.source_retained"))
    pause()



def run_big_archive_test_cockpit():
    """Read-only Big Archive development window.

    Only explicitly entered files and exactly one selected block are used.
    No batch processing, Candidate write or durable-memory write happens
    inside the Matrix Cockpit.
    """
    while True:
        header()
        print("## Große Gedächtnisdatei / Big Archive")
        print("-" * 60)
        print("1) Datei read-only analysieren")
        print("2) Genau einen Block semantisch testen")
        print("3) Aktive Adapter-/Kontextwerte anzeigen")
        print(
            "4) "
            + memoria_text(
                "big_archive.import_option",
                language=memoria_current_language(),
            )
        )
        print("0) Zurück")
        print()
        print("GoldFish-Sicherung:")
        print("- Nur ein ausdrücklich eingegebener Dateipfad.")
        print("- Semantiktest verarbeitet genau einen Block.")
        print("- Kein automatischer 39-Block-Lauf.")
        print(
            "- Optionen 1-3: keine Candidate- "
            "oder MEM-Schreiboperation."
        )
        print(
            "- Option 4: genau eine explizite "
            "Ja/Nein-Entscheidung."
        )
        print("- Quelldatei bleibt unverändert.")
        print()

        choice = cockpit_input("Auswahl: ").strip().lower()

        if choice in {"0", "b"}:
            return

        if choice == "4":
            run_big_archive_guided_import()
            continue

        if choice == "1":
            raw_path = cockpit_input(
                "Expliziter Pfad zur Gedächtnisdatei "
                "(Enter = abbrechen): "
            ).strip()

            if not raw_path:
                status("Big Archive Analyse", "abgebrochen", ok=None)
                pause()
                continue

            source_path = Path(raw_path).expanduser()

            if not source_path.is_file():
                status(
                    "Big Archive Analyse",
                    f"Datei nicht gefunden: {source_path}",
                    ok=False,
                )
                pause()
                continue

            subprocess.run(
                [
                    sys.executable,
                    "tools/memoria_big_archive_section_analyzer.py",
                    "analyze",
                    "--file",
                    str(source_path),
                    "--summary-only",
                ],
                cwd=PROJECT_ROOT,
                check=False,
            )
            pause()
            continue

        if choice == "2":
            raw_path = cockpit_input(
                "Expliziter Pfad zur Gedächtnisdatei "
                "(Enter = abbrechen): "
            ).strip()

            if not raw_path:
                status("Big Archive Blocktest", "abgebrochen", ok=None)
                pause()
                continue

            source_path = Path(raw_path).expanduser()

            if not source_path.is_file():
                status(
                    "Big Archive Blocktest",
                    f"Datei nicht gefunden: {source_path}",
                    ok=False,
                )
                pause()
                continue

            raw_block = cockpit_input(
                "Blocknummer, genau ein Block: "
            ).strip()

            try:
                block_number = int(raw_block)
            except ValueError:
                status(
                    "Big Archive Blocktest",
                    "Blocknummer muss eine ganze Zahl sein",
                    ok=False,
                )
                pause()
                continue

            if block_number < 1:
                status(
                    "Big Archive Blocktest",
                    "Blocknummer muss mindestens 1 sein",
                    ok=False,
                )
                pause()
                continue

            raw_budget = cockpit_input(
                "Max Output Tokens "
                "(Enter = 20000): "
            ).strip()

            try:
                output_budget = (
                    20000
                    if not raw_budget
                    else int(raw_budget)
                )
            except ValueError:
                status(
                    "Big Archive Blocktest",
                    "Output-Budget muss eine ganze Zahl sein",
                    ok=False,
                )
                pause()
                continue

            if output_budget < 1024:
                status(
                    "Big Archive Blocktest",
                    "Output-Budget muss mindestens 1024 sein",
                    ok=False,
                )
                pause()
                continue

            print()
            print("Genau dieser eine Block wird lokal verarbeitet:")
            print(f"- Datei: {source_path}")
            print(f"- Block: {block_number}")
            print(f"- Max Output Tokens: {output_budget}")
            print("- Kein Candidate- oder MEM-Write.")
            print()

            confirm = cockpit_input(
                "Zum Start TEST eingeben: "
            ).strip()

            if confirm != "TEST":
                status(
                    "Big Archive Blocktest",
                    "nicht gestartet",
                    ok=None,
                )
                pause()
                continue

            subprocess.run(
                [
                    sys.executable,
                    "tools/memoria_big_archive_block_summarizer.py",
                    "summarize",
                    "--file",
                    str(source_path),
                    "--block",
                    str(block_number),
                    "--max-output-tokens",
                    str(output_budget),
                ],
                cwd=PROJECT_ROOT,
                check=False,
            )
            pause()
            continue

        if choice == "3":
            print()
            print("## MEMORIA Runtime Config")
            subprocess.run(
                [
                    sys.executable,
                    "tools/memoria_runtime_config_editor.py",
                    "show",
                ],
                cwd=PROJECT_ROOT,
                check=False,
            )

            print()
            print("## Runtime Adapter Config")
            subprocess.run(
                [
                    sys.executable,
                    "tools/memoria_runtime_adapter_config.py",
                    "show",
                ],
                cwd=PROJECT_ROOT,
                check=False,
            )

            print()
            print("## Aktiver llama-server Prozess")
            process_result = subprocess.run(
                ["ps", "-eo", "pid,etimes,cmd"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

            found = False

            for line in process_result.stdout.splitlines():
                if "llama-server" in line:
                    print(line)
                    found = True

            if not found:
                print("INFO kein aktiver llama-server Prozess gefunden")

            pause()
            continue

        status(
            "Big Archive Testfenster",
            "unbekannte Auswahl",
            ok=False,
        )
        pause()



def run_memory_token_usage_cockpit(engine=None):
    """Show memory-context statistics without exposing memory text."""

    header()
    print("## Memory Token Usage")
    line()
    print(
        "Es werden nur Zählwerte ausgegeben, "
        "keine Erinnerungstexte."
    )

    query = cockpit_input("Suchanfrage: ").strip()

    if not query:
        status(
            "Memory Token Usage",
            "nicht gestartet: Suchanfrage ist leer",
            ok=None,
        )
        pause()
        return

    try:
        if engine is None:
            from context_engine.manager import ContextEngineManager

            engine = ContextEngineManager()

        result = engine.analyze_memory_token_usage(
            query=query,
        )

    except Exception as exc:
        status(
            "Memory Token Usage",
            f"Analyse fehlgeschlagen ({type(exc).__name__})",
            ok=False,
        )
        pause()
        return

    print()
    print(
        f"Aktuelle Treffer: "
        f"{result['retrieved_entries']}"
    )
    print(
        f"Verwendete Treffer: "
        f"{result['used_entries']}"
    )
    print(
        f"Verworfene Treffer: "
        f"{result['discarded_entries']}"
    )
    print(
        f"Geschätzte Memory-Tokens: "
        f"{result['estimated_memory_tokens']}"
    )

    status(
        "Memory Token Usage",
        "Analyse abgeschlossen",
        ok=True,
    )
    pause()

def run_action(action_key):

    if action_key in RELEASE_BLOCKED_ACTIONS:
        status(
            "Release Surface",
            (
                "This cockpit action is implemented for development/testing "
                "but not enabled in the public release."
            ),
            ok=False,
        )
        pause()
        return

    if action_key == "57":
        run_big_archive_test_cockpit()
        return

    if action_key == "56":
        run_memory_trash_cockpit()
        return

    if action_key == "55":
        run_mem_undo_to_candidate_cockpit()
        return

    if action_key == "62":
        run_memory_token_usage_cockpit()
        return

    if action_key == "61":
        run_attachment_ocr_cockpit()
        return

    if action_key == "60":
        run_attachment_trash_cockpit()
        return

    if action_key == "59":
        run_attachment_import_cockpit()
        return

    if action_key == "54":
        run_user_declared_memory_import_cockpit()
        return

    if action_key == "49":
        subprocess.run([sys.executable, "tools/memoria_memory_lifecycle_menu.py"])
        return

    if action_key == "48":
        run_memory_inbox_cockpit()
        return

    if action_key == "41":
        run_user_filter_cockpit()
        return
    if action_key == "34":
        set_runtime_mode_from_cockpit("NORMAL", "Set from Matrix Cockpit.")
        return

    if action_key == "35":
        set_runtime_mode_from_cockpit("THINKING_MODE", "Set from Matrix Cockpit.")
        return

    if action_key == "36":
        set_runtime_mode_from_cockpit("SERVICE_STOP", "Set from Matrix Cockpit.", require_confirmation=True)
        return

    if action_key == "43":
        run_source_ledger_config_menu()
        return

    if action_key == "44":
        run_runtime_token_budget_menu()
        return

    if action_key == "45":
        run_runtime_adapter_config_menu()
        return

    if action_key == "46":
        run_runtime_profile_config_menu()
        return

    if action_key in TOOLS:
        title, command = TOOLS[action_key]
        run_tool(title, command)
        return

    if action_key == "4":
        show_runtime_config()
        return

    if action_key == "5":
        scan_network_markers()
        return

    if action_key == "21":
        show_latest_candidate()
        return

    if action_key == "22":
        run_memory_intake(create_candidate=False)
        return

    if action_key == "23":
        run_memory_intake(create_candidate=True)
        return

    if action_key == "25":
        run_latest_candidate_state_action("approve", "Letzten Vorschlag freigeben")
        return

    if action_key == "26":
        run_latest_candidate_state_action("reject", "Letzten Vorschlag ablehnen")
        return

    if action_key == "27":
        run_latest_candidate_state_action("archive", "Letzten Vorschlag archivieren")
        return

    if action_key == "28":
        promote_latest_approved_candidate()
        return

    if action_key == "30":
        run_memory_auto_policy_process()
        return

    header()
    status("Action", f"unknown action {action_key}", ok=False)
    pause()



def latest_candidate_id(state=None, open_only=False):
    candidate_dir = PROJECT_ROOT / "knowledge" / "memory_candidates"
    candidates = sorted(candidate_dir.glob("CAND-*.json"), reverse=True)

    for path in candidates:
        if state is None and not open_only:
            return path.stem

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        item_state = data.get("state")

        if state is not None and item_state == state:
            return path.stem

        if open_only and item_state in {"candidate", "user-approved"}:
            return path.stem

    return None


def show_latest_candidate():
    candidate_id = latest_candidate_id()
    if not candidate_id:
        header()
        print("## Letzten Vorschlag anzeigen")
        line()
        status("Erinnerungsvorschläge", "keine gefunden", ok=None)
        pause()
        return

    run_tool(
        "Letzten Vorschlag anzeigen",
        ["python3", "tools/memoria_memory_candidate_store.py", "show", candidate_id],
    )




def run_memory_auto_policy_process():
    header()
    print("## Text automatisch nach User-Filtern speichern")
    line()
    print("Nur explizit eingegebener Text wird verarbeitet.")
    print("User-Filter und config/memory_auto_policy.json entscheiden, was passiert.")
    print("Dauerhafte MEM-* Speicherung passiert nur, wenn die Policy das ausdrücklich erlaubt.")
    line()

    text = input("Text: ").strip()
    if not text:
        status("Memory Auto Policy", "kein Text eingegeben", ok=None)
        pause()
        return

    run_tool(
        "Text automatisch nach User-Filtern speichern",
        ["python3", "tools/memoria_memory_auto.py", "process", "--text", text],
    )

def run_latest_candidate_state_action(action, title):
    candidate_id = latest_candidate_id(open_only=True)
    if not candidate_id:
        header()
        print(f"## {title}")
        line()
        status("Erinnerungsvorschläge", "keine offenen Vorschläge gefunden", ok=None)
        pause()
        return

    run_tool(
        title,
        ["python3", "tools/memoria_memory_candidate_store.py", action, candidate_id],
    )


def promote_latest_approved_candidate():
    candidate_id = latest_candidate_id(state="user-approved")
    if not candidate_id:
        header()
        print("## Letzten freigegebenen Vorschlag speichern")
        line()
        status("Freigegebene Vorschläge", "keine user-approved Vorschläge gefunden", ok=None)
        print()
        print("Hinweis: Erst einen Vorschlag freigeben, dann speichern/promoten.")
        pause()
        return

    run_tool(
        "Letzten freigegebenen Vorschlag speichern",
        ["python3", "tools/memoria_memory_promote.py", "promote", candidate_id],
    )

def run_memory_intake(create_candidate=False):
    header()
    title = "Text analysieren + Vorschlag erzeugen" if create_candidate else "Text analysieren"
    print(f"## {title}")
    line()
    print("Nur explizit eingegebener Text wird verarbeitet.")
    print("Keine privaten Chatlogs werden gescannt.")
    print("Durable MEM-* wird hier nie geschrieben.")
    if create_candidate:
        print("Mit Handhebel: geeigneter Text kann CAND-* im Review-Becken erzeugen.")
    line()

    text = input("Text: ").strip()
    if not text:
        status("Memory Intake", "kein Text eingegeben", ok=None)
        pause()
        return

    command = ["python3", "tools/memoria_memory_intake.py", "analyze", "--text", text]
    if create_candidate:
        command.append("--create-candidate")

    run_tool(title, command)

def show_memory_placeholder():
    header()
    print("## Memory / Gedanken Speicherung")
    line()
    print("This area is planned for explicit user-controlled memory decisions.")
    print()
    print("Planned:")
    print("- Show Memory Status")
    print("- Show Pending Memory Suggestions")
    print("- Approve Memory")
    print("- Reject Memory")
    print("- Memory Rules / Policy")
    print("- Export / Backup Memory")
    print()
    print("MEMORIA will not store thoughts automatically from this cockpit.")
    print("The user decides what should be remembered.")
    pause()




def run_cmd_inline(command):
    """Run a command inside a submenu without the cockpit pause.

    Used for preview lists before asking for a preset id.
    """
    from pathlib import Path as _MemoriaPath
    import subprocess as _memoria_subprocess

    project_root = _MemoriaPath(__file__).resolve().parents[1]

    result = _memoria_subprocess.run(
        command,
        cwd=project_root,
        text=True,
        stdout=_memoria_subprocess.PIPE,
        stderr=_memoria_subprocess.STDOUT,
        check=False,
    )
    if result.stdout:
        print(result.stdout.rstrip())
    if result.returncode != 0:
        print(f"Command exited with code {result.returncode}")


def run_cmd(command):
    """Compatibility wrapper for cockpit submenu commands.

    Delegates execution to the existing run_tool() helper.
    """
    title = " ".join(str(part) for part in command[2:]) if len(command) > 2 else "Command"
    run_tool(title, command)





def load_memory_picker_items(
    command: str,
    expected_schema: str,
):
    """Read summarized Memory Store items through its JSON interface."""
    result = subprocess.run(
        [
            sys.executable,
            "tools/memoria_memory_store.py",
            command,
            "--json",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    output = result.stdout.strip()

    if result.returncode != 0:
        return None, output or (
            f"Memory Store exited with code {result.returncode}"
        )

    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        return None, f"invalid Memory Store JSON: {exc}"

    if not isinstance(payload, dict):
        return None, "Memory Store JSON root is not an object"

    if payload.get("schema_version") != expected_schema:
        return None, "unexpected Memory Store JSON schema"

    items = payload.get("items")

    if not isinstance(items, list):
        return None, "Memory Store JSON items are invalid"

    safe_items = []

    for item in items:
        if not isinstance(item, dict):
            return None, "Memory Store item is invalid"

        # Summaries only. Full text must never enter this picker.
        if "content" in item or "text" in item:
            return None, "Memory Store item contains forbidden full text"

        safe_items.append(item)

    return safe_items, None


def run_memory_store_action(arguments):
    """Execute one Memory Store Core action.

    Successful Core output stays hidden behind the localized Matrix CLI.
    On failure, the complete Core output remains visible for diagnosis.
    """
    result = subprocess.run(
        [
            sys.executable,
            "tools/memoria_memory_store.py",
            *arguments,
        ],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    output = result.stdout.strip()

    if result.returncode != 0 and output:
        print(output)

    return result.returncode, output


def extract_core_count(output, name):
    """Extract a non-negative name=value count from Core output."""
    marker = f"{name}="

    for line in str(output or "").splitlines():
        if marker not in line:
            continue

        value = line.split(marker, 1)[1].split(",", 1)[0].strip()

        try:
            count = int(value)
        except ValueError:
            continue

        if count >= 0:
            return count

    return None


def localized_memory_status(item, tr):
    raw_status = str(
        item.get("status") or "-"
    ).strip().lower()

    translated = tr(f"status.{raw_status}")

    if translated == f"[status.{raw_status}]":
        return raw_status

    return translated


def print_numbered_memory_items(items, tr, *, trashed=False):
    if trashed:
        print(
            tr(
                "trash.trash_items_found",
                count=len(items),
            )
        )
    else:
        print(
            tr(
                "trash.memories_found",
                count=len(items),
            )
        )

    print()

    for index, item in enumerate(items, start=1):
        title = " ".join(
            str(item.get("title") or item.get("id") or "-").split()
        )[:100]

        memory_status = localized_memory_status(
            item,
            tr,
        )

        print(f"{index}) {title}")
        print(
            "   "
            + tr(
                "trash.item_status",
                status=memory_status,
            )
        )

    print()


def choose_numbered_memory_item(items, tr, *, trashed=False):
    prompt_key = (
        "trash.choose_trash_item"
        if trashed
        else "trash.choose_memory"
    )

    while True:
        raw_choice = cockpit_input(
            tr(prompt_key)
        ).strip()

        if raw_choice in {"", "0"}:
            return None

        try:
            index = int(raw_choice)
        except ValueError:
            print(tr("trash.invalid_number"))
            continue

        if 1 <= index <= len(items):
            return items[index - 1]

        print(tr("trash.invalid_number"))


def show_selected_memory_item(item, tr, *, trashed=False):
    print()
    print(
        tr(
            "trash.selected_trash_item"
            if trashed
            else "trash.selected_memory"
        )
    )
    print("-" * 60)

    print(
        tr(
            "trash.item_title",
            title=str(item.get("title") or "-"),
        )
    )
    print(
        tr(
            "trash.item_status",
            status=localized_memory_status(item, tr),
        )
    )

    preview = str(item.get("preview") or "").strip()

    if preview:
        print(
            tr(
                "trash.item_preview",
                preview=preview,
            )
        )

    if trashed:
        print(
            tr(
                "trash.item_reason",
                reason=str(item.get("reason") or "-"),
            )
        )

    print()


def run_memory_trash_cockpit():
    """Human-facing durable-memory trash management.

    The user selects numbered summaries. Full memory text is not listed.
    Matrix CLI orchestrates the existing Memory Store Core Tool and contains
    no direct storage, move or delete logic.
    """
    language = memoria_current_language()

    def tr(key, **values):
        return memoria_text(
            key,
            language=language,
            **values,
        )

    def ask_yes_no(prompt_key):
        while True:
            answer = cockpit_input(
                tr(prompt_key)
            ).strip()

            if memoria_is_yes(
                answer,
                language=language,
            ):
                return True

            if memoria_is_no(
                answer,
                language=language,
            ):
                return False

            print(tr("common.answer_yes_no"))

    def load_memories():
        items, error = load_memory_picker_items(
            "list",
            "memory-list-v0.1",
        )

        if error:
            print(tr("trash.core_failed"))
            print(error)
            return None

        if not items:
            print(tr("trash.empty_memories"))
            return []

        return items

    def load_trash():
        items, error = load_memory_picker_items(
            "trash-list",
            "memory-trash-list-v0.1",
        )

        if error:
            print(tr("trash.core_failed"))
            print(error)
            return None

        if not items:
            print(tr("trash.empty_trash"))
            return []

        return items

    while True:
        print()
        print(f"## {tr('trash.title')}")
        print("-" * 60)
        print(f"1  {tr('trash.show_memories')}")
        print(f"2  {tr('trash.move_one')}")
        print(f"3  {tr('trash.move_disabled')}")
        print(f"4  {tr('trash.show')}")
        print(f"5  {tr('trash.purge_one')}")
        print(f"6  {tr('trash.purge_all')}")
        print(f"0  {tr('common.back')}")
        print()
        print(tr("trash.security"))
        print(
            f"- {tr('trash.policy.active_safe')}"
        )
        print(
            f"- {tr('trash.policy.hard_delete_only_trash')}"
        )
        print(
            f"- {tr('trash.policy.no_automatic_empty')}"
        )
        print()

        choice = cockpit_input(
            tr("common.selection")
        ).strip()

        if choice == "0":
            return

        if choice == "1":
            items = load_memories()

            if items:
                print_numbered_memory_items(
                    items,
                    tr,
                )

            continue

        if choice == "2":
            items = load_memories()

            if not items:
                continue

            print_numbered_memory_items(
                items,
                tr,
            )

            selected = choose_numbered_memory_item(
                items,
                tr,
            )

            if selected is None:
                print(tr("common.aborted"))
                continue

            show_selected_memory_item(
                selected,
                tr,
            )

            if not ask_yes_no("trash.confirm_move"):
                print(tr("common.aborted"))
                continue

            memory_id = str(selected.get("id") or "")

            if not memory_id.startswith("MEM-"):
                print(tr("trash.core_failed"))
                continue

            result_code, _output = run_memory_store_action([
                "trash",
                memory_id,
                "--confirm",
                memory_id[-5:],
            ])

            if result_code == 0:
                print(tr("trash.move_success"))
            else:
                print(tr("trash.core_failed"))

            continue

        if choice == "3":
            if not ask_yes_no(
                "trash.confirm_move_disabled"
            ):
                print(tr("common.aborted"))
                continue

            result_code, output = run_memory_store_action([
                "trash-disabled",
                "--confirm",
                "TRASH-DISABLED-MEMORIES",
            ])

            if result_code == 0:
                moved = extract_core_count(
                    output,
                    "moved",
                )
                print(
                    tr(
                        "trash.move_disabled_success",
                        count=moved if moved is not None else "?",
                    )
                )
            else:
                print(tr("trash.core_failed"))

            continue

        if choice == "4":
            items = load_trash()

            if items:
                print_numbered_memory_items(
                    items,
                    tr,
                    trashed=True,
                )

            continue

        if choice == "5":
            items = load_trash()

            if not items:
                continue

            print_numbered_memory_items(
                items,
                tr,
                trashed=True,
            )

            selected = choose_numbered_memory_item(
                items,
                tr,
                trashed=True,
            )

            if selected is None:
                print(tr("common.aborted"))
                continue

            show_selected_memory_item(
                selected,
                tr,
                trashed=True,
            )

            if not ask_yes_no(
                "trash.confirm_purge_one"
            ):
                print(tr("common.aborted"))
                continue

            memory_id = str(selected.get("id") or "")

            if not memory_id.startswith("MEM-"):
                print(tr("trash.core_failed"))
                continue

            result_code, _output = run_memory_store_action([
                "purge",
                memory_id,
                "--confirm",
                memory_id[-5:],
            ])

            if result_code == 0:
                print(tr("trash.purge_success"))
            else:
                print(tr("trash.core_failed"))

            continue

        if choice == "6":
            items = load_trash()

            if not items:
                continue

            print_numbered_memory_items(
                items,
                tr,
                trashed=True,
            )

            print(tr("trash.warning_purge_all"))
            print(tr("trash.active_not_affected"))
            print()

            if not ask_yes_no(
                "trash.confirm_purge_all"
            ):
                print(tr("common.aborted"))
                continue

            visible_phrase = tr(
                "trash.confirm_phrase"
            )

            confirmation = cockpit_input(
                tr(
                    "trash.confirm_phrase_prompt",
                    phrase=visible_phrase,
                )
            ).strip()

            if confirmation != visible_phrase:
                print(
                    "ABORT "
                    + tr("trash.no_change")
                )
                continue

            result_code, output = run_memory_store_action([
                "purge-all",
                "--confirm",
                "PURGE-ALL-MEMORY-TRASH",
            ])

            if result_code == 0:
                purged = extract_core_count(
                    output,
                    "purged",
                )
                print(tr("trash.purge_all_success"))

                if purged is not None:
                    print(
                        tr(
                            "trash.purge_all_count",
                            count=purged,
                        )
                    )
            else:
                print(tr("trash.core_failed"))

            continue

        print(tr("common.invalid_selection"))



def run_mem_lifecycle_cockpit():
    """Human-facing durable MEM-* lifecycle control for KI testing.

    No archive/delete/forget here. Only active/disabled state changes.
    Retrieval only uses active memories.
    """
    while True:
        print()
        print("## MEM Lifecycle / Erinnerungen aktivieren-deaktivieren")
        print("-" * 60)
        print("1  Gespeicherte Erinnerungen anzeigen")
        print("2  Erinnerung vollständig anzeigen")
        print("3  Erinnerung deaktivieren")
        print("4  Erinnerung aktivieren")
        print("5  Retrieval-Test ausführen")
        print("0  Zurück")
        print()
        print("Policy:")
        print("- active = KI/Retrieval darf die Erinnerung nutzen.")
        print("- disabled = bleibt gespeichert, KI/Retrieval ignoriert sie.")
        print("- Kein Archivieren, Löschen oder Forget in diesem Menü.")
        print("- MEM-* Archiv/Forget kommt später als eigene Safety-Struktur.")
        print("- ID oder eindeutige letzte 5+ Zeichen reichen.")
        print()

        choice = input("Auswahl: ").strip()

        if choice == "0":
            return

        if choice == "1":
            run_cmd(["python3", "tools/memoria_memory_store.py", "list"])
        elif choice == "2":
            run_cmd_inline(["python3", "tools/memoria_memory_store.py", "list"])
            memory_id = input("MEM-ID oder letzte 5+ Zeichen anzeigen: ").strip()
            if memory_id:
                run_cmd(["python3", "tools/memoria_memory_store.py", "show", memory_id])
        elif choice == "3":
            run_cmd_inline(["python3", "tools/memoria_memory_store.py", "list"])
            memory_id = input("MEM-ID oder letzte 5+ Zeichen deaktivieren: ").strip()
            if memory_id:
                run_cmd(["python3", "tools/memoria_memory_store.py", "disable", memory_id])
        elif choice == "4":
            run_cmd_inline(["python3", "tools/memoria_memory_store.py", "list"])
            memory_id = input("MEM-ID oder letzte 5+ Zeichen aktivieren: ").strip()
            if memory_id:
                run_cmd(["python3", "tools/memoria_memory_store.py", "enable", memory_id])
        elif choice == "5":
            query = input("Retrieval Suchbegriff: ").strip()
            if query:
                code = (
                    "import sys; from pathlib import Path; "
                    "p=Path.cwd(); sys.path.insert(0,str(p)); "
                    "from retrieval.manager import RetrievalManager; "
                    f"q={query!r}; hits=RetrievalManager().search(q); "
                    "print(f'QUERY: {q}'); print(f'HITS : {len(hits)}'); "
                    "[print(f'- {h.id} | {h.title}') for h in hits]"
                )
                run_cmd(["python3", "-c", code])
        else:
            print("Ungültige Auswahl.")


def parse_candidate_selection(
    raw_selection,
    total_items,
):
    """Parse 1,3,7-12 / a / alle / 0 into stable list indexes."""
    total = int(total_items)
    value = str(raw_selection or "").strip().lower()

    if total < 1:
        raise ValueError(
            "keine auswählbaren Gedächtnisdateien vorhanden"
        )

    if value in {"0", "abbrechen"}:
        return []

    if value in {"a", "alle"}:
        return list(range(1, total + 1))

    if not value:
        raise ValueError("keine Auswahl angegeben")

    selected = set()

    for raw_part in value.split(","):
        part = raw_part.strip()

        if not part:
            raise ValueError(
                "leerer Auswahlteil"
            )

        if "-" in part:
            if part.count("-") != 1:
                raise ValueError(
                    f"ungültiger Bereich: {part}"
                )

            start_text, end_text = part.split(
                "-",
                1,
            )

            if not (
                start_text.isdigit()
                and end_text.isdigit()
            ):
                raise ValueError(
                    f"ungültiger Bereich: {part}"
                )

            start = int(start_text)
            end = int(end_text)

            if start > end:
                raise ValueError(
                    f"Bereich rückwärts: {part}"
                )

            numbers = range(start, end + 1)

        else:
            if not part.isdigit():
                raise ValueError(
                    f"ungültige Nummer: {part}"
                )

            numbers = [int(part)]

        for number in numbers:
            if number < 1 or number > total:
                raise ValueError(
                    f"Nummer außerhalb der Liste: {number}"
                )

            selected.add(number)

    if not selected:
        raise ValueError(
            "keine gültige Auswahl"
        )

    return sorted(selected)


def _candidate_rows_from_list_output(output):
    """Extract only open CAND-* rows from Candidate Core output."""
    import re as _candidate_re

    pattern = _candidate_re.compile(
        r"^(CAND-[0-9]{8}-[0-9]{6}-[a-f0-9]{8})"
        r"\s+\|\s+candidate\s+\|"
    )

    rows = []
    seen = set()

    for raw_line in str(output or "").splitlines():
        line = raw_line.rstrip()
        match = pattern.match(line)

        if not match:
            continue

        candidate_id = match.group(1)

        if candidate_id in seen:
            continue

        seen.add(candidate_id)
        rows.append(
            {
                "id": candidate_id,
                "display": line,
            }
        )

    return rows


def _run_candidate_core_capture(arguments):
    """Run Candidate Store Core and return its completed process."""
    project_root = Path(__file__).resolve().parents[1]

    command = [
        sys.executable,
        str(
            project_root
            / "tools"
            / "memoria_memory_candidate_store.py"
        ),
        *arguments,
    ]

    return subprocess.run(
        command,
        cwd=project_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def run_candidate_batch_delete_cockpit():
    """Select several open CAND-* files and delegate deletion to Core."""
    import tempfile as _candidate_tempfile

    print()
    print(
        "## Mehrere Gedächtnisdateien "
        "auswählen und löschen"
    )
    print("-" * 60)
    print("Policy:")
    print("- Angezeigt werden nur offene state=candidate Dateien.")
    print("- Die Matrix enthält keine eigene Löschlogik.")
    print("- Auswahl und SHA-256-Plan gehen an den Candidate Core.")
    print("- MEM-*, Archive und freigegebene Candidates bleiben tabu.")
    print("- Nach der Auswahl folgt genau eine Batch-Bestätigung.")
    print()

    listed = _run_candidate_core_capture(
        [
            "list",
            "--state",
            "candidate",
        ]
    )

    if listed.returncode != 0:
        if listed.stdout:
            print(listed.stdout.rstrip())

        print(
            f"ABORT: Candidate-Liste endete mit "
            f"Code {listed.returncode}"
        )
        return

    rows = _candidate_rows_from_list_output(
        listed.stdout
    )

    if not rows:
        print(
            "INFO Keine offenen Gedächtnisdateien "
            "zum Löschen gefunden."
        )
        return

    for index, row in enumerate(
        rows,
        start=1,
    ):
        print(
            f"{index:03d} | {row['display']}"
        )

    print()
    print("Auswahlbeispiele:")
    print("- 1,3,7-9")
    print("- a oder alle = alle angezeigten auswählen")
    print("- 0 = abbrechen")
    print()

    raw_selection = input(
        "Nummern auswählen: "
    ).strip()

    try:
        indexes = parse_candidate_selection(
            raw_selection,
            len(rows),
        )
    except ValueError as exc:
        print(f"ABORT: {exc}")
        return

    if not indexes:
        print("Abgebrochen. Keine Datei wurde gelöscht.")
        return

    selected_ids = [
        rows[index - 1]["id"]
        for index in indexes
    ]

    print()
    print(
        f"Ausgewählt: {len(selected_ids)} "
        "Gedächtnisdatei(en)"
    )

    with _candidate_tempfile.TemporaryDirectory(
        prefix="memoria-candidate-selection-"
    ) as temporary:
        temporary_root = Path(temporary)
        manifest_path = (
            temporary_root / "selection.json"
        )
        plan_path = (
            temporary_root / "delete-plan.json"
        )

        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version":
                        "matrix-candidate-selection-v0.1",
                    "candidates": [
                        {"id": candidate_id}
                        for candidate_id in selected_ids
                    ],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        prepared = _run_candidate_core_capture(
            [
                "prepare-delete-batch",
                "--manifest",
                str(manifest_path),
                "--output",
                str(plan_path),
            ]
        )

        if prepared.stdout:
            print()
            print(prepared.stdout.rstrip())

        if prepared.returncode != 0:
            print(
                f"ABORT: Löschplan endete mit "
                f"Code {prepared.returncode}"
            )
            return

        try:
            plan = json.loads(
                plan_path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception as exc:
            print(
                f"ABORT: Löschplan nicht lesbar: {exc}"
            )
            return

        planned_count = plan.get(
            "selected_count"
        )

        if (
            not isinstance(planned_count, int)
            or planned_count < 1
        ):
            print(
                "ABORT: Löschplan enthält "
                "keine gültige Auswahl."
            )
            return

        required_confirmation = (
            f"LÖSCHEN {planned_count}"
        )

        print()
        print(
            "Diese Aktion löscht die im "
            "SHA-256-Plan fixierten CAND-* Dateien."
        )
        print(
            f"Zur Bestätigung exakt eingeben: "
            f"{required_confirmation}"
        )

        confirmation = input(
            "Bestätigung: "
        ).strip()

        if confirmation != required_confirmation:
            print(
                "Abgebrochen. Bestätigung stimmt nicht."
            )
            print("Keine Datei wurde gelöscht.")
            return

        deleted = _run_candidate_core_capture(
            [
                "delete-batch",
                "--plan",
                str(plan_path),
                "--confirm",
                confirmation,
            ]
        )

        if deleted.stdout:
            print()
            print(deleted.stdout.rstrip())

        if deleted.returncode != 0:
            print(
                f"FAIL: Batch-Löschung endete mit "
                f"Code {deleted.returncode}"
            )
            return

        print()
        print(
            "OK Auswahl wurde über den "
            "Candidate Batch Core verarbeitet."
        )



def run_memory_inbox_cockpit():
    """Human-facing Memory Inbox / Gedächtnisdateien review.

    Internally uses CAND-* review files, but the user-facing workflow is:
    yes -> save as memory, no -> archive/delete, later -> archive.
    """
    while True:
        print()
        print("## Gedächtnisdateien prüfen")
        print("-" * 60)
        print("1  Eingang anzeigen")
        print("2  Gedächtnisdatei vollständig anzeigen")
        print("3  Als Gedächtnis speichern")
        print("4  Ablehnen")
        print("5  Archiv anzeigen")
        print("6  Mehrere Gedächtnisdateien auswählen und löschen")
        print("7  Abgelehnte anzeigen und löschen")
        print("0  Zurück")
        print()
        print("Hinweis:")
        print("- ID oder eindeutige letzte 5+ Zeichen reichen.")
        print("- Als Gedächtnis speichern = intern freigeben + MEM speichern.")
        print("- Ablehnen = archivieren oder CAND-Datei löschen.")
        print("- Mehrfachauswahl nutzt den hashfixierten Candidate Batch Core.")
        print("- MEM-* wird hier nie gelöscht.")
        print()

        choice = input("Auswahl: ").strip()

        if choice == "0":
            return

        if choice == "1":
            run_cmd(["python3", "tools/memoria_memory_candidate_store.py", "list", "--state", "candidate"])
        elif choice == "2":
            run_cmd_inline(["python3", "tools/memoria_memory_candidate_store.py", "list", "--state", "candidate"])
            candidate_id = input("ID oder letzte 5+ Zeichen anzeigen: ").strip()
            if candidate_id:
                run_cmd(["python3", "tools/memoria_memory_candidate_store.py", "show", candidate_id])
        elif choice == "3":
            run_cmd_inline(["python3", "tools/memoria_memory_candidate_store.py", "list", "--state", "candidate"])
            candidate_id = input("ID oder letzte 5+ Zeichen als Gedächtnis speichern: ").strip()
            if candidate_id:
                run_cmd_inline(["python3", "tools/memoria_memory_candidate_store.py", "approve", candidate_id])
                run_cmd(["python3", "tools/memoria_memory_promote.py", "promote", candidate_id])
        elif choice == "4":
            run_cmd_inline(["python3", "tools/memoria_memory_candidate_store.py", "list", "--state", "candidate"])
            candidate_id = input("ID oder letzte 5+ Zeichen ablehnen: ").strip()
            if not candidate_id:
                continue

            print()
            print("Ablehnen als:")
            print("1  Archivieren / vielleicht später")
            print("2  Löschen / weg damit")
            print("0  Abbrechen")
            reject_choice = input("Auswahl: ").strip()

            if reject_choice == "1":
                run_cmd(["python3", "tools/memoria_memory_candidate_store.py", "archive", candidate_id])
            elif reject_choice == "2":
                confirm = input("Zur Löschung letzte 5+ Zeichen erneut eingeben: ").strip()
                if confirm:
                    run_cmd(["python3", "tools/memoria_memory_candidate_store.py", "delete", candidate_id, "--confirm", confirm])
            else:
                print("Abgebrochen.")
        elif choice == "5":
            run_cmd(["python3", "tools/memoria_memory_candidate_store.py", "list", "--state", "archived"])
        elif choice == "6":
            run_candidate_batch_delete_cockpit()
        elif choice == "7":
            run_cmd_inline([
                "python3",
                "tools/memoria_memory_candidate_store.py",
                "list",
                "--state",
                "rejected",
            ])
            candidate_id = input(
                "ID oder letzte 5+ Zeichen des abgelehnten Candidates löschen: "
            ).strip()

            if not candidate_id:
                print("Abgebrochen.")
                continue

            confirm = input(
                "Zur Löschung letzte 5+ Zeichen erneut eingeben: "
            ).strip()

            if confirm:
                run_cmd([
                    "python3",
                    "tools/memoria_memory_candidate_store.py",
                    "delete",
                    candidate_id,
                    "--confirm",
                    confirm,
                ])
            else:
                print("Abgebrochen.")
        else:
            print("Ungültige Auswahl.")



def run_mem_undo_to_candidate_cockpit():
    """Move a durable MEM-* back to its source CAND-* review item.

    Uses memoria_memory_store.py undo. No hard delete. MEM-* goes to memory_trash.
    """
    print()
    print("## MEM zurück ins Review-Becken")
    print("-" * 60)
    print("Policy:")
    print("- Nutzt den Core-Befehl: memoria_memory_store.py undo.")
    print("- Der passende CAND-* wird wieder candidate.")
    print("- Der MEM-* wird aus durable memory entfernt und nach memory_trash verschoben.")
    print("- Kein Harddelete.")
    print("- Kein Volltext wird angezeigt.")
    print()

    mem_ref = input("MEM-ID oder eindeutige Kurz-ID: ").strip()

    if not mem_ref:
        print("ABORT: keine MEM-ID angegeben.")
        return

    print()
    print("Sicherheitsbestätigung:")
    print("- Gib die letzten mindestens 5 Zeichen der MEM-ID/Kurz-ID nochmal ein.")
    print("- Beispiel: bei MEM-...-5b840e01 -> 5b840e01")
    confirm = input("Confirm suffix: ").strip()

    if len(confirm) < 5:
        print("ABORT: Bestätigung muss mindestens 5 Zeichen haben.")
        return

    command = [
        "python3",
        "tools/memoria_memory_store.py",
        "undo",
        mem_ref,
        "--confirm",
        confirm,
    ]

    run_cmd(command)

    print()
    print("Nächster Schritt:")
    print("Memory / Gedanken Speicherung -> Gedächtnisdateien prüfen")
    print("Dort sollte der zurückgesetzte CAND-* wieder im Eingang liegen.")


def _run_attachment_core_capture(arguments):
    """Delegate Attachment operations to the Core tool."""
    project_root = Path(__file__).resolve().parents[1]

    return subprocess.run(
        [
            sys.executable,
            str(
                project_root
                / "tools"
                / "memoria_attachment_store.py"
            ),
            *arguments,
        ],
        cwd=project_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )



def parse_attachment_selection(
    raw_value,
    total,
):
    """Parse 1,3,5-8 / a / alle / 0 into zero-based indexes."""
    value = str(raw_value or "").strip().lower()

    if value == "0":
        return []

    if value in {"a", "alle"}:
        return list(range(total))

    if not value:
        raise ValueError("keine Auswahl eingegeben")

    selected = []
    seen = set()

    for token in value.split(","):
        token = token.strip()

        if not token:
            raise ValueError("leerer Auswahlteil")

        if "-" in token:
            parts = token.split("-", 1)

            if (
                len(parts) != 2
                or not parts[0].isdigit()
                or not parts[1].isdigit()
            ):
                raise ValueError(
                    f"ungültiger Bereich: {token}"
                )

            first = int(parts[0])
            last = int(parts[1])

            if first > last:
                raise ValueError(
                    f"Bereich rückwärts: {token}"
                )

            numbers = range(first, last + 1)
        else:
            if not token.isdigit():
                raise ValueError(
                    f"ungültige Nummer: {token}"
                )

            numbers = [int(token)]

        for number in numbers:
            if number < 1 or number > total:
                raise ValueError(
                    f"Nummer außerhalb der Liste: {number}"
                )

            index = number - 1

            if index not in seen:
                seen.add(index)
                selected.append(index)

    return selected


def _attachment_rows_from_list_output(output):
    rows = []

    for line in str(output or "").splitlines():
        if not line.startswith("ATT-"):
            continue

        parts = [
            part.strip()
            for part in line.split(" | ")
        ]

        if len(parts) < 7:
            continue

        if parts[1] != "active":
            continue

        rows.append(
            {
                "id": parts[0],
                "role": parts[2],
                "mime": parts[3],
                "size": parts[4],
                "name": parts[5],
                "context": " | ".join(parts[6:]),
            }
        )

    return rows


def run_attachment_trash_cockpit():
    """Select active ATT-* relationships and delegate trashing."""
    print()
    print("## Attachment-/Bilder verwalten")
    print("-" * 60)
    print("Policy:")
    print("- Angezeigt werden nur aktive ATT-* Beziehungen.")
    print("- Matrix enthält keine eigene Löschlogik.")
    print("- Auswahl und SHA-256-Plan gehen an den Attachment Core.")
    print("- Binärobjekte werden nicht gelöscht.")
    print("- CAND-* und MEM-* werden nicht berührt.")
    print("- Nach der Auswahl folgt genau eine Bestätigung.")
    print()

    listed = _run_attachment_core_capture(
        ["list"]
    )

    if listed.returncode != 0:
        if listed.stdout:
            print(listed.stdout.rstrip())
        print(
            "FAIL: Attachment-Liste konnte "
            "nicht geladen werden."
        )
        return

    rows = _attachment_rows_from_list_output(
        listed.stdout
    )

    if not rows:
        print("INFO Keine aktiven Attachments gefunden.")
        return

    for index, row in enumerate(rows, start=1):
        print(
            f"{index} | {row['id']} | "
            f"{row['role']} | {row['mime']} | "
            f"{row['size']} | {row['name']} | "
            f"{row['context']}"
        )

    print()
    print("Auswahlbeispiele:")
    print("- 1,3,5-8")
    print("- a oder alle")
    print("- 0 = abbrechen")
    print()

    raw_selection = input(
        "Nummern auswählen: "
    ).strip()

    if raw_selection == "0":
        print(
            "Abgebrochen. Kein Attachment "
            "wurde ins Trash-Becken gelegt."
        )
        return

    try:
        selected_indexes = parse_attachment_selection(
            raw_selection,
            len(rows),
        )
    except ValueError as exc:
        print(f"ABORT: {exc}")
        return

    if not selected_indexes:
        print(
            "Abgebrochen. Keine Auswahl vorhanden."
        )
        return

    selected_ids = [
        rows[index]["id"]
        for index in selected_indexes
    ]

    print()
    print("Ausgewählt:")

    for selected_index in selected_indexes:
        row = rows[selected_index]
        print(
            f"{selected_index + 1} | "
            f"{row['name']} | "
            f"{row['id']}"
        )

    print()
    print(
        f"Ausgewählte ATT-* Beziehungen: "
        f"{len(selected_ids)}"
    )

    with tempfile.TemporaryDirectory(
        prefix="memoria-attachment-trash-"
    ) as temporary:
        temporary_root = Path(temporary)
        manifest_path = (
            temporary_root / "selection.json"
        )
        plan_path = (
            temporary_root / "trash-plan.json"
        )

        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version":
                        "attachment-trash-selection-v0.1",
                    "attachment_ids": selected_ids,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )

        prepared = _run_attachment_core_capture(
            [
                "prepare-trash-batch",
                "--manifest",
                str(manifest_path),
                "--output",
                str(plan_path),
            ]
        )

        if prepared.stdout:
            print()
            print(prepared.stdout.rstrip())

        if prepared.returncode != 0:
            print(
                "FAIL: Der Attachment Core konnte "
                "keinen Trash-Plan erzeugen."
            )
            return

        try:
            plan = json.loads(
                plan_path.read_text(
                    encoding="utf-8"
                )
            )
            selected_count = int(
                plan["selected_count"]
            )
        except Exception as exc:
            print(
                f"FAIL: Trash-Plan nicht lesbar: {exc}"
            )
            return

        required_confirmation = (
            f"LÖSCHEN {selected_count}"
        )

        print()
        print(
            "Zur Bestätigung exakt eingeben: "
            f"{required_confirmation}"
        )

        confirmation = input(
            "Bestätigung: "
        ).strip()

        if confirmation != required_confirmation:
            print(
                "Abgebrochen. Bestätigung stimmt nicht."
            )
            return

        trashed = _run_attachment_core_capture(
            [
                "trash-batch",
                "--plan",
                str(plan_path),
                "--confirm",
                confirmation,
            ]
        )

        if trashed.stdout:
            print()
            print(trashed.stdout.rstrip())

        if trashed.returncode != 0:
            print(
                "FAIL: Attachment Core konnte "
                "den Plan nicht ausführen."
            )
            return

    print()
    print(
        "OK Ausgewählte ATT-* Beziehungen "
        "liegen im Trash-Becken."
    )
    print(
        "OK Keine Binärobjekte wurden gelöscht."
    )



def _attachment_inbox_rows():
    """List only visible top-level regular files."""
    import mimetypes
    from memoria_memory_source_ledger import (
        configured_inbox,
    )

    inbox = configured_inbox()

    if not inbox.exists():
        return inbox, []

    if not inbox.is_dir():
        raise ValueError(
            "Die konfigurierte Import-Inbox "
            "ist kein Verzeichnis."
        )

    rows = []

    for item in sorted(
        inbox.iterdir(),
        key=lambda value: value.name.casefold(),
    ):
        if item.name.startswith("."):
            continue

        if item.is_symlink():
            continue

        if not item.is_file():
            continue

        try:
            size_bytes = item.stat().st_size
        except OSError:
            continue

        if size_bytes <= 0:
            continue

        mime_type = (
            mimetypes.guess_type(item.name)[0]
            or "application/octet-stream"
        )

        rows.append(
            {
                "path": item,
                "name": item.name,
                "size_bytes": size_bytes,
                "mime_type": mime_type,
                "role": (
                    "source-image"
                    if mime_type.startswith("image/")
                    else "source-file"
                ),
            }
        )

    return inbox, rows


def _attachment_size_text(size_bytes):
    value = int(size_bytes)

    if value < 1024:
        return f"{value} B"

    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KiB"

    return f"{value / (1024 * 1024):.1f} MiB"



def _run_local_ocr_capture(arguments):
    """Delegate read-only OCR to the local OCR Core."""
    return subprocess.run(
        [
            sys.executable,
            str(
                PROJECT_ROOT
                / "tools"
                / "memoria_local_ocr.py"
            ),
            *arguments,
        ],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
        check=False,
    )


def run_attachment_ocr_cockpit():
    """Read selected inbox images without persisting OCR results."""
    supported_extensions = {
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        ".webp",
    }

    print()
    print("## Ausgewählte Bilder lesen / OCR")
    print("-" * 60)
    print("Policy:")
    print("- Nur Bilder der kontrollierten Import-Inbox werden angezeigt.")
    print("- Keine Pfadeingabe und kein privater Verzeichnis-Scan.")
    print("- Es werden ausschließlich ausgewählte Bilder gelesen.")
    print("- OCR läuft vollständig lokal mit Tesseract.")
    print("- OCR-Ergebnisse werden nicht gespeichert.")
    print("- Es entstehen keine Candidates und keine MEM-*.")
    print()

    try:
        _inbox, rows = _attachment_inbox_rows()
    except (OSError, ValueError) as exc:
        print(f"ABORT: Import-Inbox nicht lesbar: {exc}")
        return

    image_rows = [
        row
        for row in rows
        if row["path"].suffix.lower()
        in supported_extensions
    ]

    if not image_rows:
        print(
            "INFO Keine unterstützten Bilder "
            "in der Import-Inbox gefunden."
        )
        return

    for index, row in enumerate(
        image_rows,
        start=1,
    ):
        print(
            f"{index} | "
            f"{row['name']} | "
            f"{_attachment_size_text(row['size_bytes'])} | "
            f"{row['mime_type']}"
        )

    print()
    print("Auswahlbeispiele:")
    print("- 1,3,5-8")
    print("- a oder alle")
    print("- 0 = abbrechen")
    print()

    raw_selection = input(
        "Bilder auswählen: "
    ).strip()

    if raw_selection == "0":
        print(
            "Abgebrochen. Kein Bild wurde gelesen."
        )
        return

    try:
        selected_indexes = parse_attachment_selection(
            raw_selection,
            len(image_rows),
        )
    except ValueError as exc:
        print(f"ABORT: {exc}")
        return

    if not selected_indexes:
        print(
            "Abgebrochen. Kein Bild wurde ausgewählt."
        )
        return

    selected_rows = [
        image_rows[index]
        for index in selected_indexes
    ]

    print()
    print("Ausgewählt:")

    for selected_index in selected_indexes:
        row = image_rows[selected_index]

        print(
            f"{selected_index + 1} | "
            f"{row['name']}"
        )

    status_counts = {
        "recognized": 0,
        "uncertain": 0,
        "no-text": 0,
    }
    failed = 0

    for position, row in enumerate(
        selected_rows,
        start=1,
    ):
        print()
        print(
            f"===== Bild {position}: "
            f"{row['name']} ====="
        )

        try:
            completed = _run_local_ocr_capture(
                [
                    "read",
                    str(row["path"]),
                    "--language",
                    "deu+eng",
                    "--psm",
                    "6",
                    "--json",
                ]
            )
        except subprocess.TimeoutExpired:
            failed += 1
            print(
                "FAIL OCR-Zeitlimit überschritten."
            )
            continue

        raw_output = completed.stdout or ""

        if completed.returncode != 0:
            failed += 1

            if raw_output:
                print(raw_output.rstrip())

            continue

        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            failed += 1
            print(
                "FAIL Ungültige OCR-JSON-Ausgabe: "
                f"{exc}"
            )
            continue

        status_name = str(
            payload.get("status") or ""
        )

        if status_name not in status_counts:
            failed += 1
            print(
                "FAIL Unbekannter OCR-Status: "
                f"{status_name or '(leer)'}"
            )
            continue

        status_counts[status_name] += 1

        quality = payload.get("quality") or {}

        if not isinstance(quality, dict):
            quality = {}

        word_count = quality.get(
            "word_count",
            0,
        )
        average = quality.get(
            "average_confidence"
        )

        print(f"OCR-Status: {status_name}")
        print(f"OCR-Wörter: {word_count}")

        if average is None:
            print("Confidence Durchschnitt: n/a")
        else:
            print(
                "Confidence Durchschnitt: "
                f"{float(average):.2f}"
            )

        if status_name == "recognized":
            print(
                "OK Text mit ausreichender "
                "OCR-Qualität erkannt."
            )
        elif status_name == "uncertain":
            print(
                "WARN Ich konnte den Text auf "
                "diesem Bild nicht zuverlässig "
                "erkennen. Bitte Ergebnis prüfen."
            )
        else:
            print("INFO Kein Text erkannt.")

        print()
        print("Erkannter Text:")
        print("-" * 60)

        recognized_text = str(
            payload.get("text") or ""
        ).strip()

        if recognized_text:
            print(recognized_text)
        else:
            print("INFO Kein Text erkannt.")

        print("-" * 60)

    processed = sum(status_counts.values())

    print()
    print("===== OCR-ZUSAMMENFASSUNG =====")
    print(f"OCR gelesen: {processed}")
    print(
        "Erkannt:     "
        f"{status_counts['recognized']}"
    )
    print(
        "Unsicher:    "
        f"{status_counts['uncertain']}"
    )
    print(
        "Kein Text:   "
        f"{status_counts['no-text']}"
    )
    print(f"Fehler:      {failed}")
    print("OCR-Ergebnisse gespeichert: nein")
    print("Candidates erzeugt: 0")
    print("Durable Memories geschrieben: 0")

    if failed:
        print(
            "WARN Mindestens ein Bild konnte "
            "nicht gelesen werden."
        )
        return

    print()
    print(
        "OK Ausgewählte Bilder wurden "
        "lokal und read-only gelesen."
    )



def run_attachment_import_cockpit():
    """Import selected files from the explicit managed inbox."""
    from datetime import datetime, timezone
    import uuid

    print()
    print("## Bilder/Dateien übernehmen")
    print("-" * 60)
    print("Policy:")
    print("- Nur Dateien der kontrollierten Import-Inbox werden angezeigt.")
    print("- Keine Pfadeingabe und kein privater Verzeichnis-Scan.")
    print("- Versteckte Dateien, Symlinks und Unterordner werden ignoriert.")
    print("- MEMORIA interpretiert oder analysiert die Inhalte nicht.")
    print("- Die Quelldateien bleiben in der Inbox erhalten.")
    print("- Es entsteht kein automatischer Candidate und kein MEM-*.")
    print()

    try:
        _inbox, rows = _attachment_inbox_rows()
    except (OSError, ValueError) as exc:
        print(f"ABORT: Import-Inbox nicht lesbar: {exc}")
        return

    if not rows:
        print(
            "INFO Keine übernehmbaren Dateien "
            "in der Import-Inbox gefunden."
        )
        return

    for index, row in enumerate(rows, start=1):
        print(
            f"{index} | "
            f"{row['name']} | "
            f"{_attachment_size_text(row['size_bytes'])} | "
            f"{row['mime_type']}"
        )

    print()
    print("Auswahlbeispiele:")
    print("- 1,3,5-8")
    print("- a oder alle")
    print("- 0 = abbrechen")
    print()

    raw_selection = input(
        "Dateien auswählen: "
    ).strip()

    if raw_selection == "0":
        print(
            "Abgebrochen. Keine Datei wurde übernommen."
        )
        return

    try:
        selected_indexes = parse_attachment_selection(
            raw_selection,
            len(rows),
        )
    except ValueError as exc:
        print(f"ABORT: {exc}")
        return

    if not selected_indexes:
        print(
            "Abgebrochen. Keine Datei wurde ausgewählt."
        )
        return

    selected_rows = [
        rows[index]
        for index in selected_indexes
    ]

    print()
    print("Ausgewählt:")

    for display_number, row in zip(
        (
            index + 1
            for index in selected_indexes
        ),
        selected_rows,
    ):
        print(
            f"{display_number} | "
            f"{row['name']} | "
            f"{_attachment_size_text(row['size_bytes'])} | "
            f"{row['mime_type']}"
        )

    print()
    answer = input(
        f"Diese {len(selected_rows)} Datei(en) "
        "übernehmen? [ja/nein]: "
    ).strip().lower()

    if answer not in {"ja", "j", "yes", "y"}:
        print(
            "Abgebrochen. Keine Datei wurde übernommen."
        )
        return

    token = (
        datetime.now(timezone.utc).strftime(
            "%Y%m%d-%H%M%S"
        )
        + "-"
        + uuid.uuid4().hex[:8]
    )

    conversation_ref = (
        f"CONV-ATTACHMENT-INBOX-{token}"
    )

    successful = 0
    failed = 0

    print()
    print("Übernahme:")

    for position, row in enumerate(
        selected_rows,
        start=1,
    ):
        message_ref = (
            f"MSG-ATTACHMENT-INBOX-"
            f"{token}-{position:03d}"
        )

        completed = _run_attachment_core_capture(
            [
                "add",
                str(row["path"]),
                "--conversation-ref",
                conversation_ref,
                "--message-ref",
                message_ref,
                "--role",
                row["role"],
            ]
        )

        if completed.returncode == 0:
            successful += 1
            print(
                f"OK   {position} | {row['name']}"
            )
            continue

        failed += 1
        print(
            f"FAIL {position} | {row['name']}"
        )

        if completed.stdout:
            print(completed.stdout.rstrip())

    print()
    print(f"Übernommen: {successful}")
    print(f"Fehler:     {failed}")
    print("Quelldateien erhalten: ja")
    print("Automatische Candidates: 0")
    print("Automatische durable Memories: 0")

    if failed:
        print(
            "WARN Mindestens eine ausgewählte "
            "Datei konnte nicht übernommen werden."
        )
        return

    print()
    print(
        "OK Ausgewählte Bilder/Dateien wurden "
        "über den Attachment Core übernommen."
    )



def run_user_declared_memory_import_cockpit():
    """Import an explicitly user-declared memory file into the review inbox.

    This calls the core import tool. No private directory scan. No direct durable MEM-* write.
    """
    print()
    print("## Gedächtnisdatei importieren")
    print("-" * 60)
    print("Policy:")
    print("- Nur eine ausdrücklich angegebene Datei wird gelesen.")
    print("- Keine privaten Ordner werden automatisch gescannt.")
    print("- Import erzeugt CAND-* im Gedächtnisdateien-Eingang.")
    print("- Kein direktes durable MEM-* aus dem Import.")
    print()

    raw_path = input("Pfad zur Gedächtnisdatei: ").strip()

    if not raw_path:
        print("ABORT: kein Pfad angegeben.")
        return

    file_path = Path(raw_path).expanduser()

    if not file_path.is_file():
        print(f"ABORT: Datei nicht gefunden: {file_path}")
        return

    try:
        size = file_path.stat().st_size
    except Exception:
        size = 0

    print()
    print("Datei:")
    print(f"- Pfad: {file_path}")
    print(f"- Größe: {size} bytes")
    print(f"- Typ: {file_path.suffix or '(ohne Endung)'}")
    print()

    answer = input("Diese Datei als Gedächtnisdatei übernehmen? [ja/nein]: ").strip().lower()

    if answer not in {"ja", "j", "yes", "y"}:
        print("ABORT: Import abgebrochen. Keine Gedächtnisdatei erzeugt.")
        return

    command = [
        "python3",
        "tools/memoria_memory_file_import.py",
        "import",
        "--file",
        str(file_path),
        "--apply",
        "--import-mode",
        "user-declared",
        "--confirm",
        "ja",
    ]

    run_cmd(command)

    print()
    print("Nächster Schritt:")
    print("Memory / Gedanken Speicherung -> Gedächtnisdateien prüfen")
    print("Dort kannst du die importierten CAND-* ansehen und als MEM speichern.")

def run_user_filter_cockpit():
    """MEMORIA User Filter Cockpit.

    Read/write actions are delegated to Core Tools.
    This menu does not edit Python files and does not create durable memory.
    """
    while True:
        print()
        print("## User Filter / Filtermaschine")
        print("-" * 60)
        print("1  Standard Presets anzeigen")
        print("2  Aktivierte Presets anzeigen")
        print("3  Preset Details anzeigen")
        print("4  Preset aktivieren")
        print("5  Preset deaktivieren")
        print("6  Custom Filter anzeigen")
        print("7  Custom Filter hinzufügen")
        print("8  Custom Filter löschen")
        print("9  Text durch Memory Intake prüfen")
        print("10 Attachment-/Bild-Erinnerungen anzeigen")
        print("11 Attachment-/Bild-Erinnerungen einschalten")
        print("12 Attachment-/Bild-Erinnerungen ausschalten")
        print("0  Zurück")
        print()
        print("Policy:")
        print("- Presets und Custom Filter erzeugen nur Candidates.")
        print("- Keine direkte durable memory Speicherung.")
        print("- Runtime Guard kann Candidate Writes blockieren.")
        print("- Attachment-/Bild-Erinnerungen sind standardmäßig EIN.")
        print("- AUS blockiert nur neue ATT-* Schreibvorgänge.")
        print("- Vorhandene Attachments bleiben erhalten.")
        print()

        choice = input("Auswahl: ").strip()

        if choice == "0":
            return

        if choice == "1":
            run_cmd(["python3", "tools/memoria_user_filter_config.py", "presets", "list"])
        elif choice == "2":
            run_cmd(["python3", "tools/memoria_user_filter_config.py", "presets", "enabled"])
        elif choice == "3":
            preset = input("Preset ID: ").strip()
            if preset:
                run_cmd(["python3", "tools/memoria_user_filter_config.py", "presets", "show", preset])
        elif choice == "4":
            run_cmd_inline(["python3", "tools/memoria_user_filter_config.py", "presets", "list"])
            preset = input("Preset ID aus Liste aktivieren: ").strip()
            if preset:
                run_cmd(["python3", "tools/memoria_user_filter_config.py", "presets", "enable", preset])
        elif choice == "5":
            run_cmd_inline(["python3", "tools/memoria_user_filter_config.py", "presets", "enabled"])
            preset = input("Preset ID aus aktivierter Liste deaktivieren: ").strip()
            if preset:
                run_cmd(["python3", "tools/memoria_user_filter_config.py", "presets", "disable", preset])
        elif choice == "6":
            run_cmd(["python3", "tools/memoria_user_filter_config.py", "custom", "list"])
        elif choice == "7":
            term = input("Custom Filter Begriff hinzufügen: ").strip()
            if term:
                run_cmd(["python3", "tools/memoria_user_filter_config.py", "custom", "add", "--term", term])
        elif choice == "8":
            term = input("Custom Filter Begriff löschen: ").strip()
            if term:
                run_cmd(["python3", "tools/memoria_user_filter_config.py", "custom", "del", "--term", term])
        elif choice == "9":
            text = input("Text für Intake Dry-run: ").strip()
            if text:
                run_cmd(["python3", "tools/memoria_memory_intake.py", "analyze", "--text", text])
        elif choice == "10":
            run_cmd([
                "python3",
                "tools/memoria_user_filter_config.py",
                "attachments",
                "status",
            ])
        elif choice == "11":
            run_cmd([
                "python3",
                "tools/memoria_user_filter_config.py",
                "attachments",
                "enable",
            ])
        elif choice == "12":
            run_cmd([
                "python3",
                "tools/memoria_user_filter_config.py",
                "attachments",
                "disable",
            ])
        else:
            print("Ungültige Auswahl.")

def show_group_menu(group_title, action_keys):
    while True:
        entries = [
            f"{index}) {action_label(action_key)}"
            for index, action_key in enumerate(action_keys, start=1)
        ]
        entries.extend(["", "b) Back"])

        render_navigation_frame(group_title, entries)
        choice = read_navigation_choice()

        if choice == "b":
            return

        if choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(action_keys):
                action_key = action_keys[index]
                leave_navigation_screen()
                run_action(action_key)
                remember_last_action(action_label(action_key))
                continue

        leave_navigation_screen()
        print("Unknown selection.")
        pause()


def menu():
    while True:
        entries = [
            f"{key}) {title}"
            for key, title, _actions in MENU_GROUPS
        ]
        entries.extend(["", "q) Quit"])

        render_navigation_frame("MAIN MENU", entries)
        choice = read_navigation_choice()

        if choice == "q":
            leave_navigation_screen()
            print("MEMORIA Matrix Cockpit closed.")
            return 0

        handled = False

        for key, title, actions in MENU_GROUPS:
            if choice == key:
                handled = True

                if actions:
                    show_group_menu(title, actions)
                elif title == "Memory / Gedanken Speicherung":
                    leave_navigation_screen()
                    show_memory_placeholder()
                else:
                    show_group_menu(title, actions)

                break

        if handled:
            continue

        leave_navigation_screen()
        print("Unknown selection.")
        pause()

if __name__ == "__main__":
    try:
        matrix_intro()
        sys.exit(menu())
    except KeyboardInterrupt:
        leave_navigation_screen()
        print()
        print("MEMORIA Matrix Cockpit closed by user.")
        sys.exit(0)
