#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / "tools"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from memoria_storage_paths import managed_path


SOURCE_LEDGER_CONFIG = Path(
    os.environ.get(
        "MEMORIA_MEMORY_SOURCE_LEDGER_CONFIG",
        str(PROJECT_ROOT / "config" / "memory_source_ledger.json"),
    )
)

DEFAULT_SOURCE_LEDGER_CONFIG = {
    "schema_version": "memory-source-ledger-config-v0.1",
    "enabled": False,
    "inbox": "",
    "poll_interval_seconds": 60,
    "min_poll_interval_seconds": 10,
}


SERVICE_NAMES = ("source_ledger_watch", "openwebui_context_server")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_import_inbox() -> Path:
    return managed_path(
        "imports",
        env_var="MEMORIA_IMPORT_DIR",
        fallback_rel="imports",
    ) / "inbox"


def require_selected_storage_mounted() -> None:
    """
    Prevent writes to an unmounted external storage path.

    If the Memory Storage Manager is in an external mode and the selected
    storage root appears to be on the system root filesystem, abort instead
    of silently writing to the master M.2.
    """
    try:
        from memoria_memory_storage_manager import load_config, resolve_storage_root

        config = load_config()
        mode = str(config.get("mode", "project-local"))
        root = resolve_storage_root(config)

        if mode != "project-local":
            if not root.exists():
                raise SystemExit(f"ABORT selected MEMORIA storage root does not exist: {root}")

            if root.stat().st_dev == Path("/").stat().st_dev:
                raise SystemExit(
                    "ABORT selected MEMORIA storage root appears to be on the system filesystem. "
                    "Is the external/dedicated memory storage mounted?"
                )
    except SystemExit:
        raise
    except Exception:
        # Do not block project-local/dev fallback if the storage manager is unavailable.
        pass



def service_root() -> Path:
    base = managed_path("logs", env_var="MEMORIA_LOG_DIR", fallback_rel="logs")
    root = base / "services"
    root.mkdir(parents=True, exist_ok=True)
    return root


def pid_path(service: str) -> Path:
    return service_root() / f"{service}.pid.json"


def log_path(service: str) -> Path:
    return service_root() / f"{service}.log"


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    data = dict(default)

    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        data.update(loaded)

    return data


def load_source_ledger_config() -> dict[str, Any]:
    return load_json(SOURCE_LEDGER_CONFIG, DEFAULT_SOURCE_LEDGER_CONFIG)


def is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def read_pid_info(service: str) -> dict[str, Any] | None:
    path = pid_path(service)

    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"service": service, "pid": None, "corrupt": True}


def write_pid_info(service: str, info: dict[str, Any]) -> None:
    path = pid_path(service)
    tmp = path.with_suffix(".pid.json.tmp")
    tmp.write_text(json.dumps(info, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def remove_pid_info(service: str) -> None:
    try:
        pid_path(service).unlink()
    except FileNotFoundError:
        pass


def build_source_ledger_watch_command() -> tuple[list[str], dict[str, Any]]:
    config = load_source_ledger_config()

    require_selected_storage_mounted()
    inbox = str(config.get("inbox") or default_import_inbox())
    interval = int(config.get("poll_interval_seconds", 60))
    minimum = int(config.get("min_poll_interval_seconds", 10))

    if interval < minimum:
        raise SystemExit(f"ABORT source_ledger_watch interval must be >= {minimum} seconds")

    command = [
        sys.executable,
        str(PROJECT_ROOT / "tools" / "memoria_memory_source_ledger.py"),
        "watch",
        "--inbox",
        inbox,
        "--interval",
        str(interval),
    ]

    return command, {
        "enabled": bool(config.get("enabled", False)),
        "inbox": inbox,
        "interval": interval,
        "config": str(SOURCE_LEDGER_CONFIG),
    }



def docker_gateway_host() -> str:
    """Return the Docker bridge host IP used by OpenWebUI containers."""
    return os.environ.get("MEMORIA_CONTEXT_HOST", "172.17.0.1")


def build_openwebui_context_server_command() -> tuple[list[str], dict[str, Any]]:
    host = docker_gateway_host()
    port = int(os.environ.get("MEMORIA_CONTEXT_PORT", "8765"))

    command = [
        sys.executable,
        str(PROJECT_ROOT / "tools" / "memoria_openwebui_context_server.py"),
        "serve",
        "--host",
        host,
        "--port",
        str(port),
    ]

    return command, {
        "enabled": True,
        "host": host,
        "port": port,
        "url": f"http://{host}:{port}/context",
        "health": f"http://{host}:{port}/health",
        "policy": "context-only, no secrets, no writes, no OpenWebUI chatlog scan",
    }


def service_definition(service: str) -> dict[str, Any]:
    if service == "source_ledger_watch":
        command, config = build_source_ledger_watch_command()
        return {
            "name": service,
            "label": "Source Ledger Watch",
            "command": command,
            "enabled": config["enabled"],
            "config": config,
        }

    if service == "openwebui_context_server":
        command, config = build_openwebui_context_server_command()
        return {
            "name": service,
            "label": "OpenWebUI Context Server",
            "command": command,
            "enabled": config["enabled"],
            "config": config,
        }

    raise SystemExit(f"ABORT unknown service: {service}")


def service_status(service: str) -> dict[str, Any]:
    definition = service_definition(service)
    pid_info = read_pid_info(service)

    pid = None
    running = False
    stale = False

    if pid_info:
        try:
            pid = int(pid_info.get("pid"))
        except Exception:
            pid = None

        if pid is not None:
            running = is_pid_running(pid)

        stale = bool(pid_info) and not running

    return {
        "service": service,
        "label": definition["label"],
        "enabled": definition["enabled"],
        "running": running,
        "stale_pid_file": stale,
        "pid": pid,
        "pid_file": str(pid_path(service)),
        "log_file": str(log_path(service)),
        "config": definition["config"],
    }


def all_status() -> dict[str, Any]:
    return {
        "version": "memoria-service-manager-v0.1",
        "service_root": str(service_root()),
        "services": [service_status(name) for name in SERVICE_NAMES],
        "safety": {
            "no_systemd_enable": True,
            "no_private_directory_scan": True,
            "service_autostart_requires_config": True,
        },
    }


def start_service(service: str, force: bool = False) -> dict[str, Any]:
    definition = service_definition(service)
    current = service_status(service)

    if current["running"]:
        return {"ok": True, "service": service, "action": "start", "result": "already-running", "pid": current["pid"]}

    if current["stale_pid_file"]:
        remove_pid_info(service)

    if not definition["enabled"] and not force:
        return {"ok": False, "service": service, "action": "start", "result": "disabled", "message": "service disabled in config"}

    log_file = log_path(service)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    with log_file.open("a", encoding="utf-8") as log:
        log.write(f"\n--- {utc_now()} starting {service} ---\n")
        log.flush()

        process = subprocess.Popen(
            definition["command"],
            cwd=str(PROJECT_ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=os.environ.copy(),
            text=True,
        )

    info = {
        "schema_version": "memoria-service-pid-v0.1",
        "service": service,
        "pid": process.pid,
        "started_at": utc_now(),
        "command": definition["command"],
        "log_file": str(log_file),
    }
    write_pid_info(service, info)

    time.sleep(0.2)
    running = is_pid_running(process.pid)

    return {
        "ok": running,
        "service": service,
        "action": "start",
        "result": "running" if running else "failed",
        "pid": process.pid,
        "log_file": str(log_file),
    }


def stop_service(service: str) -> dict[str, Any]:
    current = service_status(service)
    pid = current.get("pid")

    if not pid:
        remove_pid_info(service)
        return {"ok": True, "service": service, "action": "stop", "result": "not-running"}

    if not current["running"]:
        remove_pid_info(service)
        return {"ok": True, "service": service, "action": "stop", "result": "stale-pid-removed", "pid": pid}

    try:
        os.kill(int(pid), signal.SIGTERM)
    except ProcessLookupError:
        remove_pid_info(service)
        return {"ok": True, "service": service, "action": "stop", "result": "already-stopped", "pid": pid}

    for _ in range(20):
        if not is_pid_running(int(pid)):
            remove_pid_info(service)
            return {"ok": True, "service": service, "action": "stop", "result": "stopped", "pid": pid}
        time.sleep(0.1)

    try:
        os.kill(int(pid), signal.SIGKILL)
    except ProcessLookupError:
        pass

    remove_pid_info(service)
    return {"ok": True, "service": service, "action": "stop", "result": "killed", "pid": pid}


def start_enabled_services() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for service in SERVICE_NAMES:
        if service_definition(service)["enabled"]:
            results.append(start_service(service))
        else:
            results.append({"ok": True, "service": service, "action": "start-enabled", "result": "disabled-skip"})

    return results


def stop_all_services() -> list[dict[str, Any]]:
    return [stop_service(service) for service in SERVICE_NAMES]


def apply_runtime_services(mode: str) -> list[dict[str, Any]]:
    normalized = mode.strip().upper()

    if normalized == "NORMAL":
        return start_enabled_services()

    if normalized in {"SERVICE_STOP", "THINKING_MODE"}:
        return stop_all_services()

    raise SystemExit(f"ABORT unsupported runtime mode for service apply: {mode}")


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))


def print_status(data: dict[str, Any]) -> None:
    print("MEMORIA SERVICE MANAGER V0.1")
    print("-" * 48)
    print("Controls MEMORIA background services. No systemd enable/start.")
    print(f"Service root: {data['service_root']}")
    print()

    for item in data["services"]:
        if item["running"]:
            state = f"running pid={item['pid']}"
        elif item["stale_pid_file"]:
            state = "stale pid file"
        elif not item["enabled"]:
            state = "disabled"
        else:
            state = "stopped"

        print(f"{item['service']}: {state}")
        print(f"  enabled: {item['enabled']}")
        print(f"  log: {item['log_file']}")
        if item["service"] == "source_ledger_watch":
            print(f"  inbox: {item['config']['inbox']}")
            print(f"  interval: {item['config']['interval']}s")


def command_status(args: argparse.Namespace) -> int:
    data = all_status()
    if args.json:
        print_json(data)
    else:
        print_status(data)
    return 0


def command_start(args: argparse.Namespace) -> int:
    result = start_service(args.service, force=args.force)
    if args.json:
        print_json(result)
    else:
        print(f"{'OK' if result.get('ok') else 'FAIL'} {result['service']} start: {result['result']}")
        if result.get("message"):
            print(result["message"])
        if result.get("pid"):
            print(f"PID: {result['pid']}")
        if result.get("log_file"):
            print(f"Log: {result['log_file']}")
    return 0 if result.get("ok") else 23


def command_stop(args: argparse.Namespace) -> int:
    result = stop_service(args.service)
    if args.json:
        print_json(result)
    else:
        print(f"{'OK' if result.get('ok') else 'FAIL'} {result['service']} stop: {result['result']}")
    return 0 if result.get("ok") else 23


def command_health(args: argparse.Namespace) -> int:
    definition = service_definition(args.service)
    health_url = str(definition.get("config", {}).get("health") or "").strip()

    if not health_url:
        print(f"FAIL {args.service} health: no health endpoint configured")
        return 23

    try:
        with urllib.request.urlopen(health_url, timeout=5) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"FAIL {args.service} health: {exc}")
        return 23

    print(body)
    return 0


def command_start_enabled(args: argparse.Namespace) -> int:
    results = start_enabled_services()
    if args.json:
        print_json(results)
    else:
        for result in results:
            print(f"{'OK' if result.get('ok') else 'FAIL'} {result['service']}: {result['result']}")
    return 0 if all(item.get("ok") for item in results) else 23


def command_stop_all(args: argparse.Namespace) -> int:
    results = stop_all_services()
    if args.json:
        print_json(results)
    else:
        for result in results:
            print(f"{'OK' if result.get('ok') else 'FAIL'} {result['service']}: {result['result']}")
    return 0 if all(item.get("ok") for item in results) else 23


def command_apply_runtime(args: argparse.Namespace) -> int:
    results = apply_runtime_services(args.mode)
    if args.json:
        print_json(results)
    else:
        for result in results:
            print(f"{'OK' if result.get('ok') else 'FAIL'} {result['service']}: {result['result']}")
    return 0 if all(item.get("ok") for item in results) else 23


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MEMORIA service manager")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=command_status)

    start = sub.add_parser("start")
    start.add_argument("service", choices=SERVICE_NAMES)
    start.add_argument("--force", action="store_true")
    start.add_argument("--json", action="store_true")
    start.set_defaults(func=command_start)

    stop = sub.add_parser("stop")
    stop.add_argument("service", choices=SERVICE_NAMES)
    stop.add_argument("--json", action="store_true")
    stop.set_defaults(func=command_stop)

    health = sub.add_parser("health")
    health.add_argument(
        "service",
        choices=("openwebui_context_server",),
    )
    health.set_defaults(func=command_health)

    start_enabled = sub.add_parser("start-enabled")
    start_enabled.add_argument("--json", action="store_true")
    start_enabled.set_defaults(func=command_start_enabled)

    stop_all = sub.add_parser("stop-all")
    stop_all.add_argument("--json", action="store_true")
    stop_all.set_defaults(func=command_stop_all)

    apply_runtime = sub.add_parser("apply-runtime")
    apply_runtime.add_argument("mode", choices=("NORMAL", "THINKING_MODE", "SERVICE_STOP"))
    apply_runtime.add_argument("--json", action="store_true")
    apply_runtime.set_defaults(func=command_apply_runtime)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
