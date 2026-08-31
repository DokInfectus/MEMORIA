#!/usr/bin/env python3

"""
MEMORIA Operations Status V0.3

Read-only graphical information cockpit for MEMORIA.

Principles:
- no config changes
- no private content display
- no sniffing / packet capture
- no hidden network actions
- existing CLI tools remain the source of truth
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from memoria_i18n import current_language as memoria_current_language


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "runtime.json"

OPERATIONS_STATUS_INTERVAL_MS = 30000
NVIDIA_WATCH_INTERVAL_MS = 2000

MATRIX_UI_DEFAULT_GEOMETRY = "1680x960"
MATRIX_UI_MIN_WIDTH = 1320
MATRIX_UI_MIN_HEIGHT = 780
SIDEBAR_WIDTH = 320
SIDEBAR_BUTTON_WRAP = SIDEBAR_WIDTH - 44

MATRIX_UI_VIEWPORT_RATIO = 1.0
MATRIX_UI_MAX_WIDTH = 2400
MATRIX_UI_MAX_HEIGHT = 1400
MATRIX_UI_MARGIN_PX = 12

MATRIX_UI_SIDEBAR_LABELS = {
    "Core / Live Tests": ("Core / Live Tests", "Kern / Live-Tests"),
    "Runtime Smoke Test": ("Runtime Smoke Test", "Runtime-Kurztest"),
    "Adapter Live Test": ("Adapter Live Test", "Adapter-Live-Test"),
    "Prompt Engine Live Test": ("Prompt Engine Live Test", "Prompt-Engine-Live-Test"),
    "Memory Live Test": ("Memory Live Test", "Gedächtnis-Live-Test"),
    "Open WebUI Memory Live Test": ("Open WebUI Memory Live Test", "Open-WebUI-Gedächtnis-Live-Test"),
    "Open WebUI Adapter Live Test": ("Open WebUI Adapter Live Test", "Open-WebUI-Adapter-Live-Test"),
    "Configuration / Model": ("Configuration / Model", "Konfiguration / Modell"),
    "Runtime Config": ("Runtime Config", "Runtime-Konfiguration"),
    "Runtime Config neu laden": ("Reload Runtime Config", "Runtime-Konfiguration neu laden"),
    "Runtime Token Budgets anzeigen": ("Show Runtime Token Budgets", "Runtime-Token-Budgets anzeigen"),
    "Runtime Adapter Config anzeigen": ("Show Runtime Adapter Config", "Runtime-Adapter-Konfiguration anzeigen"),
    "Runtime Profile Config anzeigen": ("Show Runtime Profile Config", "Runtime-Profil-Konfiguration anzeigen"),
    "Memory / Gedanken": ("Memory / Thoughts", "Gedächtnis / Gedanken"),
    "Memory Placeholder": ("Memory Placeholder", "Gedächtnis-Platzhalter"),
    "Gespeicherte Erinnerungen": ("Stored Memories", "Gespeicherte Erinnerungen"),
    "Erinnerungen suchen": ("Search Memories", "Erinnerungen suchen"),
    "Erinnerungsvorschläge": ("Memory Suggestions", "Erinnerungsvorschläge"),
    "Freigegebene Vorschläge": ("Approved Suggestions", "Freigegebene Vorschläge"),
    "Archivierte Vorschläge": ("Archived Suggestions", "Archivierte Vorschläge"),
    "Memory Storage Watchdog": ("Memory Storage Watchdog", "Gedächtnisspeicher-Watchdog"),
    "Memory Storage Watchdog Check": ("Check Memory Storage Watchdog", "Gedächtnisspeicher-Watchdog prüfen"),
    "Letzten Vorschlag anzeigen": ("Show Latest Suggestion", "Letzten Vorschlag anzeigen"),
    "System / Hardware": ("System / Hardware", "System / Hardware"),
    "System / Hardware Snapshot": ("System / Hardware Snapshot", "System-/Hardware-Snapshot"),
    "Security / Visibility": ("Security / Visibility", "Sicherheit / Sichtbarkeit"),
    "Network / Sync Visibility": ("Network / Sync Visibility", "Netzwerk-/Sync-Sichtbarkeit"),
    "Docker / Tunnel Visibility": ("Docker / Tunnel Visibility", "Docker-/Tunnel-Sichtbarkeit"),
    "Open WebUI API Key Status": ("Open WebUI API Key Status", "Open WebUI API-Schlüsselstatus"),
    "Matrix UI Control": ("Matrix UI Control", "Matrix-UI-Steuerung"),
    "Matrix UI Doctor": ("Matrix UI Doctor", "Matrix-UI-Diagnose"),
    "Matrix UI Status": ("Matrix UI Status", "Matrix-UI-Status"),
    "Patch / USB Tools": ("Patch / USB Tools", "Patch-/USB-Werkzeuge"),
    "USB Patch Finder": ("USB Patch Finder", "USB-Patch-Finder"),
}


SAFE_RUNTIME_KEYS = [
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


TEST_TOOLS = {
    "runtime": ("Runtime Smoke Test", ["python3", "tools/memoria_runtime_smoke_test.py"]),
    "adapter": ("Adapter Live Test", ["python3", "tools/memoria_adapter_live_test.py"]),
    "prompt": ("Prompt Engine Live Test", ["python3", "tools/memoria_prompt_engine_live_test.py"]),
    "memory_live": ("Memory Live Test", ["python3", "tools/memoria_memory_live_test.py"]),
    "openwebui_memory_live": ("Open WebUI Memory Live Test", ["python3", "tools/memoria_openwebui_memory_live_test.py"]),
    "openwebui_adapter_live": ("Open WebUI Adapter Live Test", ["python3", "tools/memoria_openwebui_adapter_live_test.py"]),
    "network": ("Network / Sync Visibility Scan", ["python3", "tools/memoria_matrix_cockpit.py", "--scan-only"]),
    "docker_visibility": ("Docker / Tunnel Visibility", ["python3", "tools/memoria_docker_visibility.py"]),
    "openwebui_key_status": ("Open WebUI API Key Status", ["python3", "tools/memoria_openwebui_key_setup.py", "status"]),
    "runtime_config_show": ("Runtime Config anzeigen", ["python3", "tools/memoria_runtime_config_editor.py", "show"]),
    "runtime_token_budgets_show": ("Runtime Token Budgets anzeigen", ["python3", "tools/memoria_runtime_config_editor.py", "show"]),
    "runtime_adapter_config_show": ("Runtime Adapter Config anzeigen", ["python3", "tools/memoria_runtime_adapter_config.py", "show"]),
    "runtime_profile_config_show": ("Runtime Profile Config anzeigen", ["python3", "tools/memoria_runtime_profile_config.py", "show"]),
    "memory_list": ("Gespeicherte Erinnerungen", ["python3", "tools/memoria_memory_store.py", "list"]),
    "memory_search_benutzer": ("Erinnerungen suchen: Benutzer", ["python3", "tools/memoria_memory_store.py", "search", "Benutzer"]),
    "memory_storage_watchdog_status": ("Memory Storage Watchdog", ["python3", "tools/memoria_memory_storage_watchdog.py", "status"]),
    "memory_storage_watchdog_check": ("Memory Storage Watchdog Check", ["python3", "tools/memoria_memory_storage_watchdog.py", "check"]),
    "memory_candidate_list": ("Erinnerungsvorschläge", ["python3", "tools/memoria_memory_candidate_store.py", "list"]),
    "memory_candidate_approved": ("Freigegebene Vorschläge", ["python3", "tools/memoria_memory_candidate_store.py", "list", "--state", "user-approved"]),
    "memory_candidate_archived": ("Archivierte Vorschläge", ["python3", "tools/memoria_memory_candidate_store.py", "list", "--state", "archived"]),
    "hardware": ("System / Hardware Snapshot", ["python3", "tools/memoria_system_snapshot.py"]),
    "model_selection": ("LLM Model Selection", ["python3", "tools/memoria_model_selection.py"]),
    "usb": ("USB Patch Finder", ["python3", "tools/memoria_usb_patch_finder.py"]),
    "ui_doctor": ("Matrix UI Doctor", ["python3", "tools/memoria_matrix_ui_doctor.py"]),
    "ui_status": ("Matrix UI Control Status", ["python3", "tools/memoria_matrix_ui_control.py", "status"]),
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


THEME = {
    "bg": "#030b0b",
    "panel": "#071515",
    "panel2": "#0b2020",
    "line": "#1c3b38",
    "line2": "#1d6d35",
    "green": "#55ff4d",
    "green2": "#38d447",
    "green3": "#0d3518",
    "text": "#d8f5e5",
    "muted": "#8ca79b",
    "warn": "#ffb84d",
    "bad": "#ff5c5c",
    "cyan": "#46d9ff",
}



MATRIX_UI_STATUS_VALUES = {
    "ready": ("Ready", "Bereit"),
    "online": ("Online", "Online"),
    "operational": ("Operational", "Betriebsbereit"),
    "read_only_scan": (
        "Read-only Scan",
        "Read-only-Prüfung",
    ),
    "completed": ("Completed", "Abgeschlossen"),
    "config_error": (
        "Config Error",
        "Konfigurationsfehler",
    ),
    "scanning": ("Scanning", "Prüfung läuft"),
    "n_a": ("N/A", "Nicht anwendbar"),
    "running": ("Running", "Läuft"),
    "failed": ("Failed", "Fehlgeschlagen"),
}


MATRIX_UI_STATUS_CARD_TITLES = {
    "runtime": ("RUNTIME", "LAUFZEIT"),
    "adapter": ("ADAPTER", "ADAPTER"),
    "prompt": ("PROMPT ENGINE", "PROMPT-ENGINE"),
    "network": ("NETWORK VISIBILITY", "NETZWERK-SICHTBARKEIT"),
    "hardware": ("HARDWARE SNAPSHOT", "HARDWARE-SNAPSHOT"),
}


MATRIX_UI_PANEL_TITLES = {
    "RUNTIME CONFIG": (
        "RUNTIME CONFIG",
        "RUNTIME-KONFIGURATION",
    ),
    "FUNCTION TEST OUTPUT": (
        "FUNCTION TEST OUTPUT",
        "FUNKTIONSTEST-AUSGABE",
    ),
    "NVIDIA WATCH": (
        "NVIDIA WATCH",
        "NVIDIA-STATUS",
    ),
    "SYSTEM / HARDWARE SNAPSHOT": (
        "SYSTEM / HARDWARE SNAPSHOT",
        "SYSTEM-/HARDWARE-SNAPSHOT",
    ),
}


LLAMACPP_ONLY_TEST_ALTERNATIVES = {
    "runtime": "openwebui_adapter_live",
    "prompt": "openwebui_adapter_live",
    "memory_live": "openwebui_memory_live",
}





def safe_read_runtime_config():
    if not CONFIG_PATH.exists():
        return {}, "runtime.json not found"

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, str(exc)

    safe = {}

    for key in SAFE_RUNTIME_KEYS:
        if key in data:
            safe[key] = data[key]

    return safe, None


def run_command(command, timeout=120):
    try:
        result = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )

        return result.returncode, result.stdout

    except subprocess.TimeoutExpired:
        return 124, f"Timeout after {timeout} seconds"
    except Exception as exc:
        return 1, str(exc)


def scan_network_markers():
    hits = []

    for path in PROJECT_ROOT.rglob("*.py"):
        parts = set(path.parts)

        if "__pycache__" in parts:
            continue

        if ".git" in parts:
            continue

        if ".backup" in parts:
            continue

        if "backup" in path.name.lower() or ".bak" in path.name.lower():
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        lowered = text.lower()

        for marker in NETWORK_MARKERS:
            if marker in lowered:
                hits.append((str(path.relative_to(PROJECT_ROOT)), marker))
                break

    lines = [
        "MEMORIA NETWORK / SYNC VISIBILITY SCAN",
        "-" * 60,
        "This is a visibility scan only.",
        "It does not inspect user traffic and does not capture packets.",
        "",
    ]

    if not hits:
        lines.append("OK  Network Markers: none found")
    else:
        lines.append(f"INFO Network Markers: {len(hits)} file(s) contain network/sync markers")

        for rel_path, marker in hits:
            lines.append(f"INFO {rel_path}: marker '{marker}'")

    lines.extend([
        "",
        "Allowed examples:",
        "- local llama.cpp calls to 127.0.0.1 / localhost",
        "- explicit user-requested install/update checks",
        "- explicit diagnostics shown to the user",
        "",
        "Not allowed:",
        "- hidden telemetry",
        "- private data uploads",
        "- traffic sniffing",
        "- background sync without user action",
    ])

    return "\n".join(lines)


def read_first_match(path, prefix):
    file_path = Path(path)

    if not file_path.exists():
        return None

    try:
        for line_text in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line_text.startswith(prefix):
                return line_text.split(":", 1)[1].strip()
    except Exception:
        return None

    return None


def read_meminfo():
    values = {}

    path = Path("/proc/meminfo")

    if not path.exists():
        return values

    try:
        for line_text in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if ":" not in line_text:
                continue

            key, value = line_text.split(":", 1)
            parts = value.strip().split()

            if not parts:
                continue

            try:
                values[key] = int(parts[0])
            except ValueError:
                continue

    except Exception:
        return {}

    return values


def format_kib(value):
    if value is None:
        return "unknown"

    return f"{value / 1024 / 1024:.2f} GiB"


def collect_hardware_snapshot():
    meminfo = read_meminfo()

    data = {
        "Hostname": platform.node() or "unknown",
        "OS": platform.platform(),
        "Kernel": platform.release(),
        "Python": platform.python_version(),
        "CPU": read_first_match("/proc/cpuinfo", "model name") or platform.processor() or "unknown",
        "Logical Cores": str(os.cpu_count() or "unknown"),
        "RAM Total": format_kib(meminfo.get("MemTotal")),
        "RAM Available": format_kib(meminfo.get("MemAvailable")),
        "Swap Total": format_kib(meminfo.get("SwapTotal")),
    }

    try:
        usage = shutil.disk_usage("/")
        data["Root Total"] = f"{usage.total / 1024**3:.2f} GiB"
        data["Root Used"] = f"{usage.used / 1024**3:.2f} GiB"
        data["Root Free"] = f"{usage.free / 1024**3:.2f} GiB"
    except Exception:
        data["Root Disk"] = "unknown"

    gpu_rows = []

    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used,temperature.gpu,power.draw,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]

    try:
        result = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=5,
        )

        if result.returncode == 0:
            for row in result.stdout.splitlines():
                row = row.strip()

                if not row:
                    continue

                parts = [part.strip() for part in row.split(",")]

                while len(parts) < 6:
                    parts.append("unknown")

                name, mem_total, mem_used, temp, power, util = parts[:6]

                gpu_rows.append({
                    "name": name,
                    "mem_total": mem_total,
                    "mem_used": mem_used,
                    "temp": temp,
                    "power": power,
                    "util": util,
                })

    except Exception:
        pass

    return data, gpu_rows


def build_hardware_text():
    data, gpus = collect_hardware_snapshot()

    lines = [
        "MEMORIA SYSTEM / HARDWARE SNAPSHOT",
        "-" * 60,
        "Read-only local system snapshot. No config changes. No private content.",
        "",
        "## System",
        "-" * 60,
    ]

    for key, value in data.items():
        lines.append(f"OK  {key}: {value}")

    lines.append("")
    lines.append("## GPU")
    lines.append("-" * 60)

    if not gpus:
        lines.append("INFO NVIDIA: nvidia-smi not found or no GPU rows returned")
    else:
        for index, gpu in enumerate(gpus, start=1):
            lines.append(f"OK  GPU {index}: {gpu['name']}")
            lines.append(f"OK  GPU {index} VRAM: {gpu['mem_used']} / {gpu['mem_total']} MiB")
            lines.append(f"OK  GPU {index} Temp: {gpu['temp']} C")
            lines.append(f"OK  GPU {index} Power: {gpu['power']} W")
            lines.append(f"OK  GPU {index} Util: {gpu['util']} %")

    lines.append("")
    lines.append("## Result")
    lines.append("-" * 60)
    lines.append("OK  System Snapshot: completed")

    return "\n".join(lines)


def build_nvidia_watch_text():
    _data, gpus = collect_hardware_snapshot()

    lines = [
        "MEMORIA NVIDIA WATCH V0.1",
        "-" * 60,
        "Read-only NVIDIA GPU status. 2s live tracker. No config changes. No private content.",
        f"Updated: {time.strftime('%H:%M:%S')}",
        "",
    ]

    if not gpus:
        lines.append("INFO NVIDIA: nvidia-smi not found or no GPU rows returned")
        return "\n".join(lines)

    for index, gpu in enumerate(gpus, start=1):
        lines.append(
            f"GPU {index}: {gpu['name']} | "
            f"VRAM {gpu['mem_used']} / {gpu['mem_total']} MiB | "
            f"{gpu['temp']} C | {gpu['power']} W | {gpu['util']} %"
        )

    return "\n".join(lines)



def build_function_test_start_text(language="en"):
    if language == "de":
        lines = [
            "MEMORIA FUNKTIONSTEST-AUSGABE",
            "-" * 60,
            "Bereit.",
            "Starte einen Funktionstest über die linke Seitenleiste.",
            "",
            "Dieses Feld zeigt ausschließlich Funktionstest-Ausgaben.",
            "Hardwarestatus steht im SYSTEM-/HARDWARE-SNAPSHOT.",
            "GPU-Status steht im NVIDIA-STATUS.",
            "",
            "Richtlinie:",
            "- Dieses Feld ändert keine Konfiguration.",
            "- Es werden keine privaten Inhalte angezeigt.",
            "- Hier werden keine Hardware-Snapshot-Protokolle ausgegeben.",
            "",
        ]
    else:
        lines = [
            "MEMORIA FUNCTION TEST OUTPUT",
            "-" * 60,
            "Ready.",
            "Run a function test from the left sidebar.",
            "",
            "This panel shows function test output only.",
            "Hardware status is shown in SYSTEM / HARDWARE SNAPSHOT.",
            "GPU live status is shown in NVIDIA WATCH.",
            "",
            "Policy:",
            "- No config changes are performed by this panel.",
            "- No private content is displayed.",
            "- No hardware snapshot logs are dumped here.",
            "",
        ]

    return "\n".join(lines)


def build_memory_placeholder_text(language="en"):
    if language == "de":
        lines = [
            "MEMORIA GEDÄCHTNIS / GEDANKEN",
            "-" * 60,
            "Dieser Bereich ist für ausdrücklich vom Benutzer "
            "gesteuerte Gedächtnisentscheidungen vorgesehen.",
            "",
            "Geplant:",
            "- Gedächtnisstatus anzeigen",
            "- Offene Erinnerungsvorschläge anzeigen",
            "- Erinnerung freigeben",
            "- Erinnerung ablehnen",
            "- Gedächtnisregeln / Richtlinie",
            "- Gedächtnis exportieren / sichern",
            "",
            "MEMORIA speichert über diese Oberfläche keine "
            "Gedanken automatisch.",
            "Der Benutzer entscheidet, was erinnert werden soll.",
        ]
    else:
        lines = [
            "MEMORIA MEMORY / THOUGHTS",
            "-" * 60,
            "This area is planned for explicit user-controlled "
            "memory decisions.",
            "",
            "Planned:",
            "- Show Memory Status",
            "- Show Pending Memory Suggestions",
            "- Approve Memory",
            "- Reject Memory",
            "- Memory Rules / Policy",
            "- Export / Backup Memory",
            "",
            "MEMORIA will not store thoughts automatically "
            "from this UI.",
            "The user decides what should be remembered.",
        ]

    return "\n".join(lines)

class MatrixUI(tk.Tk):
    def __init__(self):
        super().__init__()

        try:
            self.ui_language = memoria_current_language()
        except (Exception, SystemExit):
            self.ui_language = "en"

        if self.ui_language == "de":
            self.title("MEMORIA Betriebsstatus V0.3")
        else:
            self.title("MEMORIA Operations Status V0.3")
        self.geometry(MATRIX_UI_DEFAULT_GEOMETRY)
        self.minsize(MATRIX_UI_MIN_WIDTH, MATRIX_UI_MIN_HEIGHT)
        self.configure(bg=THEME["bg"])

        self.status_codes = {
            "runtime": "ready",
            "adapter": "online",
            "prompt": "operational",
            "network": "read_only_scan",
            "hardware": "completed",
        }

        self.status_vars = {
            key: tk.StringVar(
                value=self._status_text(status_code)
            )
            for key, status_code in self.status_codes.items()
        }

        self.status_card_title_labels = {}

        self.function_output_is_idle = True

        self.test_state = {
            "runtime": "unknown",
            "adapter": "unknown",
            "prompt": "unknown",
            "network": "unknown",
            "hardware": "unknown",
        }

        self._build_layout()
        self.refresh_runtime()
        self.refresh_hardware()
        self.refresh_nvidia_watch()
        self.reset_function_test_output()
        self.after(NVIDIA_WATCH_INTERVAL_MS, self.refresh_nvidia_watch_loop)
        self.after(100, self.apply_browser_autofit)

    def _ui_text(self, english, german):
        return german if self.ui_language == "de" else english

    def _sidebar_text(self, source_text):
        labels = MATRIX_UI_SIDEBAR_LABELS.get(source_text)
        if labels is None:
            return source_text
        return labels[1] if self.ui_language == "de" else labels[0]

    def _status_card_title_text(self, key):
        titles = MATRIX_UI_STATUS_CARD_TITLES.get(key)
        if titles is None:
            return key
        return titles[1] if self.ui_language == "de" else titles[0]

    def _panel_title_text(self, source_text):
        titles = MATRIX_UI_PANEL_TITLES.get(source_text)
        if titles is None:
            return source_text
        return titles[1] if self.ui_language == "de" else titles[0]

    def _status_text(self, status_code):
        values = MATRIX_UI_STATUS_VALUES.get(status_code)

        if values is None:
            return str(status_code)

        return values[1] if self.ui_language == "de" else values[0]

    def _set_status(self, key, status_code):
        self.status_codes[key] = status_code

        status_var = self.status_vars.get(key)

        if status_var is not None:
            status_var.set(
                self._status_text(status_code)
            )

    def _refresh_localized_status_values(self):
        for key, status_code in self.status_codes.items():
            status_var = self.status_vars.get(key)

            if status_var is not None:
                status_var.set(
                    self._status_text(status_code)
                )

    def _refresh_localized_titles(self):
        for key, label in getattr(
            self,
            "status_card_title_labels",
            {},
        ).items():
            label.configure(
                text=self._status_card_title_text(key)
            )

        for panel_name in (
            "runtime_panel",
            "test_panel",
            "network_panel",
            "hardware_panel",
        ):
            panel = getattr(self, panel_name, None)
            if panel is None:
                continue

            label = getattr(
                panel,
                "_memoria_panel_header_label",
                None,
            )
            source_title = getattr(
                panel,
                "_memoria_panel_title_source",
                None,
            )

            if label is not None and source_title is not None:
                label.configure(
                    text=self._panel_title_text(source_title)
                )

    def _rebuild_sidebar(self):
        try:
            position = float(self.sidebar_canvas.yview()[0])
        except Exception:
            position = 0.0

        for child in self.sidebar.winfo_children():
            child.destroy()

        self._build_sidebar()
        self.sidebar.update_idletasks()
        self._on_sidebar_configure()
        self.sidebar_canvas.yview_moveto(position)

    def toggle_ui_language(self):
        self.ui_language = "en" if self.ui_language == "de" else "de"

        self.title(
            self._ui_text(
                "MEMORIA Operations Status V0.3",
                "MEMORIA Betriebsstatus V0.3",
            )
        )

        self.header_title_label.configure(
            text=self._ui_text(
                "MEMORIA OPERATIONS STATUS",
                "MEMORIA BETRIEBSSTATUS",
            )
        )

        self.header_subtitle_label.configure(
            text=self._ui_text(
                "Read-only operations dashboard · 30s status tracker · "
                "No config changes · No private content",
                "Read-only Betriebsübersicht · 30-s-Statusanzeige · "
                "Keine Konfigurationsänderungen · Keine privaten Inhalte",
            )
        )

        self.header_badge_label.configure(
            text=self._ui_text(
                "● Operational",
                "● Betriebsbereit",
            )
        )

        self.language_button.configure(
            text=f"DE / EN · {self.ui_language.upper()}"
        )
        self._rebuild_sidebar()
        self._refresh_localized_titles()
        self._refresh_localized_status_values()

        if getattr(
            self,
            "function_output_is_idle",
            False,
        ):
            self.reset_function_test_output()

    def card(self, parent, title):
        frame = tk.Frame(
            parent,
            bg=THEME["panel"],
            highlightbackground=THEME["line"],
            highlightthickness=1,
            bd=0,
        )

        label = tk.Label(
            frame,
            text=self._panel_title_text(title),
            bg=THEME["panel"],
            fg=THEME["green"],
            font=("Consolas", 12, "bold"),
            anchor="w",
        )
        label._memoria_panel_header = True
        frame._memoria_panel_header_label = label
        frame._memoria_panel_title_source = title
        label.pack(fill="x", padx=12, pady=(10, 4))

        return frame

    def _build_layout(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self.sidebar_container = tk.Frame(self, bg="#061111", width=SIDEBAR_WIDTH)
        self.sidebar_container.grid(row=0, column=0, sticky="ns")
        self.sidebar_container.grid_propagate(False)
        self.sidebar_container.grid_rowconfigure(0, weight=1)
        self.sidebar_container.grid_columnconfigure(0, weight=1)

        self.sidebar_canvas = tk.Canvas(
            self.sidebar_container,
            bg="#061111",
            width=SIDEBAR_WIDTH,
            highlightthickness=0,
            borderwidth=0,
        )
        self.sidebar_scrollbar = ttk.Scrollbar(
            self.sidebar_container,
            orient="vertical",
            command=self.sidebar_canvas.yview,
        )

        self.sidebar = tk.Frame(self.sidebar_canvas, bg="#061111")
        self.sidebar_window = self.sidebar_canvas.create_window(
            (0, 0),
            window=self.sidebar,
            anchor="nw",
        )

        self.sidebar_canvas.configure(
            yscrollcommand=self.sidebar_scrollbar.set
        )
        self.sidebar_canvas.grid(row=0, column=0, sticky="nsew")
        self.sidebar_scrollbar.grid(row=0, column=1, sticky="ns")

        self.sidebar.bind("<Configure>", self._on_sidebar_configure)
        self.sidebar_canvas.bind("<Configure>", self._on_sidebar_canvas_configure)
        self.sidebar_canvas.bind("<MouseWheel>", self._on_sidebar_mousewheel)
        self.sidebar_canvas.bind("<Button-4>", self._on_sidebar_mousewheel)
        self.sidebar_canvas.bind("<Button-5>", self._on_sidebar_mousewheel)

        self.main = tk.Frame(self, bg=THEME["bg"])
        self.main.grid(row=0, column=1, sticky="nsew", padx=12, pady=10)
        self.main.columnconfigure(0, weight=1)
        self.main.rowconfigure(2, weight=1)

        self._build_sidebar()
        self._build_header()
        self._build_status_cards()
        self._build_content()

    def _on_sidebar_configure(self, _event=None):
        self.sidebar_canvas.configure(
            scrollregion=self.sidebar_canvas.bbox("all")
        )

    def _on_sidebar_canvas_configure(self, event):
        self.sidebar_canvas.itemconfigure(
            self.sidebar_window,
            width=event.width,
        )

    def _on_sidebar_mousewheel(self, event):
        if getattr(event, "num", None) == 4:
            self.sidebar_canvas.yview_scroll(-3, "units")
        elif getattr(event, "num", None) == 5:
            self.sidebar_canvas.yview_scroll(3, "units")
        elif getattr(event, "delta", 0):
            self.sidebar_canvas.yview_scroll(
                int(-1 * (event.delta / 120)),
                "units",
            )

    def _build_sidebar(self):
        logo = tk.Label(
            self.sidebar,
            text=self._ui_text(
                "MEMORIA\nOPERATIONS\nSTATUS\nV0.3",
                "MEMORIA\nBETRIEBS\nSTATUS\nV0.3",
            ),
            bg="#061111",
            fg=THEME["green"],
            font=("Consolas", 24, "bold"),
            justify="left",
        )
        logo.pack(anchor="w", padx=18, pady=(22, 18))

        def heading(text):
            label = tk.Label(
                self.sidebar,
                text=self._sidebar_text(text),
                bg="#061111",
                fg=THEME["cyan"],
                font=("Consolas", 10, "bold"),
                anchor="w",
            )
            label.pack(fill="x", padx=18, pady=(12, 2))

        def button(text, command):
            item = tk.Button(
                self.sidebar,
                text=self._sidebar_text(text),
                command=command,
                anchor="w",
                bg=THEME["panel"],
                fg=THEME["text"],
                activebackground=THEME["green3"],
                activeforeground=THEME["green"],
                relief="flat",
                bd=0,
                padx=14,
                pady=9,
                font=("Consolas", 10),
                wraplength=SIDEBAR_BUTTON_WRAP,
                justify="left",
                highlightbackground=THEME["line"],
                highlightthickness=1,
            )
            item.pack(fill="x", padx=14, pady=3)

        heading("Core / Live Tests")
        button("Runtime Smoke Test", lambda: self.run_named_tool("runtime"))
        button("Adapter Live Test", lambda: self.run_named_tool("adapter"))
        button("Prompt Engine Live Test", lambda: self.run_named_tool("prompt"))
        button("Memory Live Test", lambda: self.run_named_tool("memory_live"))
        button("Open WebUI Memory Live Test", lambda: self.run_named_tool("openwebui_memory_live"))
        button("Open WebUI Adapter Live Test", lambda: self.run_named_tool("openwebui_adapter_live"))

        heading("Configuration / Model")
        button("Runtime Config", lambda: self.run_named_tool("runtime_config_show"))
        button("Runtime Config neu laden", self.reload_runtime_config)
        button("Runtime Token Budgets anzeigen", lambda: self.run_named_tool("runtime_token_budgets_show"))
        button("Runtime Adapter Config anzeigen", lambda: self.run_named_tool("runtime_adapter_config_show"))
        button("Runtime Profile Config anzeigen", lambda: self.run_named_tool("runtime_profile_config_show"))

        heading("Memory / Gedanken")
        button("Memory Placeholder", self.show_memory_placeholder)
        button("Gespeicherte Erinnerungen", lambda: self.run_named_tool("memory_list"))
        button("Erinnerungen suchen", lambda: self.run_named_tool("memory_search_benutzer"))
        button("Erinnerungsvorschläge", lambda: self.run_named_tool("memory_candidate_list"))
        button("Freigegebene Vorschläge", lambda: self.run_named_tool("memory_candidate_approved"))
        button("Archivierte Vorschläge", lambda: self.run_named_tool("memory_candidate_archived"))
        button("Memory Storage Watchdog", lambda: self.run_named_tool("memory_storage_watchdog_status"))
        button("Memory Storage Watchdog Check", lambda: self.run_named_tool("memory_storage_watchdog_check"))
        button("Letzten Vorschlag anzeigen", self.show_latest_memory_candidate)

        heading("System / Hardware")
        button("System / Hardware Snapshot", self.refresh_hardware)

        heading("Security / Visibility")
        button("Network / Sync Visibility", self.run_network_scan)
        button("Docker / Tunnel Visibility", lambda: self.run_named_tool("docker_visibility"))
        button("Open WebUI API Key Status", lambda: self.run_named_tool("openwebui_key_status"))

        heading("Matrix UI Control")
        button("Matrix UI Doctor", lambda: self.run_named_tool("ui_doctor"))
        button("Matrix UI Status", lambda: self.run_named_tool("ui_status"))

        heading("Patch / USB Tools")
        button("USB Patch Finder", lambda: self.run_named_tool("usb"))

        spacer = tk.Frame(self.sidebar, bg="#061111")
        spacer.pack(fill="both", expand=True)

        protect = tk.Label(
            self.sidebar,
            text=self._ui_text(
                (
                    "MEMORIA PROTECTS YOU\n\n"
                    "No hidden telemetry.\n"
                    "No sniffing.\n"
                    "No private data collection.\n\n"
                    "Your data stays yours."
                ),
                (
                    "MEMORIA SCHÜTZT DICH\n\n"
                    "Keine versteckte Telemetrie.\n"
                    "Kein Netzwerk-Sniffing.\n"
                    "Keine Sammlung privater Daten.\n\n"
                    "Deine Daten bleiben deine."
                ),
            ),
            bg=THEME["panel"],
            fg=THEME["green"],
            justify="left",
            anchor="w",
            font=("Consolas", 10),
            padx=14,
            pady=14,
            highlightbackground=THEME["line2"],
            highlightthickness=1,
        )
        protect.pack(fill="x", padx=14, pady=(8, 18))

    def _build_header(self):
        header = tk.Frame(
            self.main,
            bg=THEME["panel"],
            highlightbackground=THEME["line"],
            highlightthickness=1,
        )
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)

        self.header_title_label = tk.Label(
            header,
            text=self._ui_text(
                "MEMORIA OPERATIONS STATUS",
                "MEMORIA BETRIEBSSTATUS",
            ),
            bg=THEME["panel"],
            fg=THEME["text"],
            font=("Consolas", 26, "bold"),
            anchor="w",
        )
        self.header_title_label.grid(
            row=0, column=0, sticky="ew", padx=20, pady=(12, 0)
        )

        self.header_subtitle_label = tk.Label(
            header,
            text=self._ui_text(
                "Read-only operations dashboard · 30s status tracker · "
                "No config changes · No private content",
                "Read-only Betriebsübersicht · 30-s-Statusanzeige · "
                "Keine Konfigurationsänderungen · Keine privaten Inhalte",
            ),
            bg=THEME["panel"],
            fg=THEME["green"],
            font=("Consolas", 11),
            anchor="w",
        )
        self.header_subtitle_label.grid(
            row=1, column=0, sticky="ew", padx=20, pady=(0, 14)
        )

        self.header_badge_label = tk.Label(
            header,
            text=self._ui_text(
                "● Operational",
                "● Betriebsbereit",
            ),
            bg=THEME["green3"],
            fg=THEME["green"],
            font=("Consolas", 11, "bold"),
            padx=14,
            pady=8,
            highlightbackground=THEME["line2"],
            highlightthickness=1,
        )
        self.header_badge_label.grid(
            row=0, column=1, rowspan=2, sticky="e",
            padx=(20, 8), pady=15,
        )

        self.language_button = tk.Button(
            header,
            text=f"DE / EN · {self.ui_language.upper()}",
            command=self.toggle_ui_language,
            bg=THEME["panel"],
            fg=THEME["cyan"],
            activebackground=THEME["green3"],
            activeforeground=THEME["green"],
            relief="solid",
            padx=10,
            pady=8,
        )
        self.language_button.grid(
            row=0, column=2, rowspan=2, sticky="e",
            padx=(0, 20), pady=15,
        )

    def _build_status_cards(self):
        row = tk.Frame(self.main, bg=THEME["bg"])
        row.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        for index in range(5):
            row.columnconfigure(index, weight=1)

        cards = [
            ("RUNTIME", "runtime"),
            ("ADAPTER", "adapter"),
            ("PROMPT ENGINE", "prompt"),
            ("NETWORK VISIBILITY", "network"),
            ("HARDWARE SNAPSHOT", "hardware"),
        ]

        for index, (title, key) in enumerate(cards):
            frame = tk.Frame(
                row,
                bg=THEME["panel"],
                highlightbackground=THEME["line"],
                highlightthickness=1,
            )
            frame.grid(row=0, column=index, sticky="ew", padx=5)

            title_label = tk.Label(
                frame,
                text=self._status_card_title_text(key),
                bg=THEME["panel"],
                fg=THEME["muted"],
                font=("Consolas", 10, "bold"),
                anchor="w",
            )
            title_label.pack(
                fill="x",
                padx=14,
                pady=(10, 0),
            )
            self.status_card_title_labels[key] = title_label

            tk.Label(
                frame,
                textvariable=self.status_vars[key],
                bg=THEME["panel"],
                fg=THEME["green"],
                font=("Consolas", 17, "bold"),
                anchor="w",
            ).pack(fill="x", padx=14, pady=(2, 12))

    def _build_content(self):
        content = tk.Frame(self.main, bg=THEME["bg"])
        content.grid(row=2, column=0, sticky="nsew")
        content.columnconfigure(0, weight=46)
        content.columnconfigure(1, weight=54)
        content.rowconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)

        self.runtime_panel = self.card(content, "RUNTIME CONFIG")
        self.runtime_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 5), pady=(0, 5))

        self.test_panel = self.card(content, "FUNCTION TEST OUTPUT")
        self.test_panel.grid(row=0, column=1, sticky="nsew", padx=(5, 0), pady=(0, 5))
        self.test_panel.rowconfigure(1, weight=1)
        self.test_panel.columnconfigure(0, weight=1)

        self.output = ScrolledText(
            self.test_panel,
            bg="#020909",
            fg=THEME["text"],
            insertbackground=THEME["green"],
            font=("Consolas", 10),
            relief="flat",
            bd=0,
            height=18,
        )
        self.output.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.network_panel = self.card(content, "NVIDIA WATCH")
        self.nvidia_watch_panel = self.network_panel
        self.network_panel.grid(row=1, column=0, sticky="nsew", padx=(0, 5), pady=(5, 0))

        self.hardware_panel = self.card(content, "SYSTEM / HARDWARE SNAPSHOT")
        self.hardware_panel.grid(row=1, column=1, sticky="nsew", padx=(5, 0), pady=(5, 0))

    def clear_panel(self, panel):
        for child in panel.winfo_children():
            if not getattr(child, "_memoria_panel_header", False):
                child.destroy()

    def set_output(self, text):
        self.function_output_is_idle = False
        self.output.delete("1.0", "end")
        self.output.insert("end", text)
        self.output.see("end")


    def find_function_output_widget(self):
        panel = getattr(self, "test_panel", None)

        if panel is None:
            return None

        stack = list(panel.winfo_children())

        while stack:
            child = stack.pop(0)

            if isinstance(child, ScrolledText):
                return child

            try:
                stack.extend(child.winfo_children())
            except Exception:
                pass

        return None

    def reset_function_test_output(self):
        box = self.find_function_output_widget()

        if box is None:
            return

        try:
            box.configure(state="normal")
        except Exception:
            pass

        box.delete("1.0", "end")
        box.insert(
            "end",
            build_function_test_start_text(
                self.ui_language
            ),
        )
        self.function_output_is_idle = True

        try:
            box.configure(state="disabled")
        except Exception:
            pass

    def append_output(self, text):
        self.function_output_is_idle = False
        self.output.insert("end", text)
        self.output.see("end")


    def apply_browser_autofit(self):
        """Fit the operations dashboard to the current VNC/browser viewport.

        Read-only UI behavior only. No config writes.
        """
        try:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()

            width = int(screen_w * MATRIX_UI_VIEWPORT_RATIO) - (MATRIX_UI_MARGIN_PX * 2)
            height = int(screen_h * MATRIX_UI_VIEWPORT_RATIO) - (MATRIX_UI_MARGIN_PX * 2)

            width = max(MATRIX_UI_MIN_WIDTH, min(width, MATRIX_UI_MAX_WIDTH))
            height = max(MATRIX_UI_MIN_HEIGHT, min(height, MATRIX_UI_MAX_HEIGHT))

            x = MATRIX_UI_MARGIN_PX
            y = MATRIX_UI_MARGIN_PX
            self.geometry(f"{width}x{height}+{x}+{y}")
            self.minsize(MATRIX_UI_MIN_WIDTH, MATRIX_UI_MIN_HEIGHT)
        except Exception:
            # Fallback for minimal/no window manager environments.
            try:
                self.geometry(MATRIX_UI_DEFAULT_GEOMETRY)
                self.minsize(MATRIX_UI_MIN_WIDTH, MATRIX_UI_MIN_HEIGHT)
            except Exception:
                pass

    def refresh_runtime(self):
        self.clear_panel(self.runtime_panel)

        data, error = safe_read_runtime_config()

        if error:
            self._kv(self.runtime_panel, "runtime.json", error, bad=True)
            self._set_status("runtime", "config_error")
            return

        for key in SAFE_RUNTIME_KEYS:
            if key in data:
                self._kv(self.runtime_panel, key, str(data[key]))

        self._set_status("runtime", "ready")


    def refresh_nvidia_watch_loop(self):
        self.refresh_nvidia_watch()
        self.after(NVIDIA_WATCH_INTERVAL_MS, self.refresh_nvidia_watch_loop)

    def refresh_nvidia_watch(self):
        panel = getattr(self, "nvidia_watch_panel", None)

        if panel is None:
            return

        self.clear_panel(panel)

        box = ScrolledText(
            panel,
            height=9,
            bg="#020808",
            fg=THEME["text"],
            insertbackground=THEME["green"],
            font=("Consolas", 9),
            relief="flat",
            borderwidth=0,
        )
        box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        box.insert("end", build_nvidia_watch_text())
        box.configure(state="disabled")

    def refresh_hardware(self):
        self.clear_panel(self.hardware_panel)

        # Full hardware snapshot is shown inside its own scroll box.
        # This keeps multi-GPU systems visible instead of clipping labels.
        hardware_text = build_hardware_text()
        self.set_output(hardware_text)

        box = ScrolledText(
            self.hardware_panel,
            bg="#020909",
            fg=THEME["text"],
            insertbackground=THEME["green"],
            font=("Consolas", 9),
            relief="flat",
            bd=0,
            height=18,
            wrap="none",
        )
        box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        box.insert("end", hardware_text)
        box.configure(state="disabled")

        self._set_status("hardware", "completed")

    def run_network_scan(self):
        self._set_status("network", "scanning")

        text = scan_network_markers()
        self.set_output(text)
        self.clear_panel(self.network_panel)

        self._subline(
            self.network_panel,
            self._ui_text(
                "Visibility scan only",
                "Nur Sichtbarkeitsprüfung",
            ),
            strong=True,
        )
        self._subline(
            self.network_panel,
            self._ui_text(
                "Does not inspect user traffic",
                "Untersucht keinen Benutzerverkehr",
            ),
        )
        self._subline(
            self.network_panel,
            self._ui_text(
                "Does not capture packets",
                "Erfasst keine Netzwerkpakete",
            ),
        )
        self._subline(
            self.network_panel,
            self._ui_text(
                "MEMORIA protects you. "
                "No hidden telemetry. No sniffing.",
                "MEMORIA schützt dich. "
                "Keine versteckte Telemetrie. Kein Sniffing.",
            ),
        )

        self._set_status("network", "read_only_scan")

    def show_memory_placeholder(self):
        self.set_output(
            build_memory_placeholder_text(
                self.ui_language
            )
        )


    def _set_test_output_text(self, text: str):
        import tkinter as tk

        self.function_output_is_idle = False
        self.output.configure(state="normal")
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, text)
        self.output.see(tk.END)

    def show_latest_memory_candidate(self):
        from pathlib import Path

        candidates = sorted(Path("knowledge/memory_candidates").glob("CAND-*.json"), reverse=True)
        if not candidates:
            self.set_output("INFO Keine Erinnerungsvorschläge gefunden.\\n")
            return

        cand_id = candidates[0].stem
        title = "Letzten Vorschlag anzeigen"
        command = ["python3", "tools/memoria_memory_candidate_store.py", "show", cand_id]

        self.set_output(f"{title}: {cand_id} wird gelesen...\\n")

        def worker():
            code, output = run_command(command)

            def finish():
                self.set_output(output)
                if code == 0:
                    self.append_output("\\nOK  Erinnerungsvorschlag angezeigt. Keine Änderung gespeichert.\\n")
                else:
                    self.append_output(f"\\nFAIL Erinnerungsvorschlag anzeigen: exit code {code}\\n")

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()


    def reload_runtime_config(self):
        self.refresh_runtime()
        self.append_output("\nOK Runtime Config neu geladen.\n")


    def run_named_tool(self, key):
        title, command = TEST_TOOLS[key]

        alternative_key = LLAMACPP_ONLY_TEST_ALTERNATIVES.get(key)

        if alternative_key is not None:
            runtime, error = safe_read_runtime_config()
            adapter = "" if error else str(runtime.get("adapter", "")).strip()

            if adapter == "OpenWebUIAdapter":
                current_title = self._sidebar_text(title)
                alternative_title = self._sidebar_text(
                    TEST_TOOLS[alternative_key][0]
                )

                self.set_output(
                    self._ui_text(
                        f"INFO {current_title}: not applicable for "
                        "OpenWebUIAdapter.\n"
                        f"Use {alternative_title}.\n"
                        "No test was started. "
                        "No configuration was changed.\n",
                        f"INFO {current_title}: für OpenWebUIAdapter "
                        "nicht anwendbar.\n"
                        f"Bitte {alternative_title} verwenden.\n"
                        "Es wurde kein Test gestartet und keine "
                        "Konfiguration geändert.\n",
                    )
                )

                if key == "runtime":
                    self.refresh_runtime()
                elif key == "prompt":
                    self._set_status("prompt", "n_a")

                return

        self.set_output(f"{title} running...\n")
        if key in self.status_vars:
            self._set_status(key, "running")

        def worker():
            code, output = run_command(command)
            self.after(0, lambda: self.finish_tool(key, title, code, output))

        threading.Thread(target=worker, daemon=True).start()

    def finish_tool(self, key, title, code, output):
        if key == "hardware":
            self.refresh_hardware()
            status = "OK" if code == 0 else f"FAIL exit code {code}"
            self.append_output(f"\n{status} {title}: refreshed in SYSTEM / HARDWARE SNAPSHOT panel\n")
            return
        self.set_output(output)

        if code == 0:
            status_code = "completed"

            if key == "runtime":
                self._set_status("runtime", "ready")
            elif key == "adapter":
                self._set_status("adapter", "online")
            elif key == "prompt":
                self._set_status("prompt", "operational")
            elif key in self.status_vars:
                self._set_status(key, status_code)

            self.append_output(f"\nOK  {title}: completed\n")
        else:
            if key in self.status_vars:
                self._set_status(key, "failed")

            self.append_output(f"\nFAIL {title}: exit code {code}\n")

    def _kv(self, parent, key, value, bad=False):
        row = tk.Frame(parent, bg=THEME["panel"])
        row.pack(fill="x", padx=14, pady=2)

        tk.Label(
            row,
            text=key,
            bg=THEME["panel"],
            fg=THEME["muted"],
            font=("Consolas", 10),
            anchor="w",
            width=30,
        ).pack(side="left")

        tk.Label(
            row,
            text=value,
            bg=THEME["panel"],
            fg=THEME["bad"] if bad else THEME["green"],
            font=("Consolas", 10),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

    def _subline(self, parent, text, strong=False, warn=False):
        tk.Label(
            parent,
            text=text,
            bg=THEME["panel"],
            fg=THEME["warn"] if warn else (THEME["green"] if strong else THEME["text"]),
            font=("Consolas", 10, "bold" if strong else "normal"),
            anchor="w",
            justify="left",
        ).pack(fill="x", padx=14, pady=2)


def main():
    if sys.platform.startswith("linux"):
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            print("INFO Matrix UI requires a graphical display.")
            print("INFO No DISPLAY or WAYLAND_DISPLAY environment variable found.")
            print("INFO Use the terminal cockpit on headless systems:")
            print("INFO   python3 tools/memoria_matrix_cockpit.py")
            return 2

    try:
        app = MatrixUI()
        app.mainloop()
    except tk.TclError as exc:
        print("INFO Matrix UI could not open a graphical display.")
        print(f"INFO {exc}")
        print("INFO Use the terminal cockpit instead:")
        print("INFO   python3 tools/memoria_matrix_cockpit.py")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
