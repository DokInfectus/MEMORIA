#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

import sys
TOOLS_DIR = PROJECT_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from memoria_storage_paths import managed_path


ALLOWED_EXTENSIONS = {".txt", ".md", ".json"}

CONFIG_PATH = Path(
    os.environ.get(
        "MEMORIA_MEMORY_SOURCE_LEDGER_CONFIG",
        str(PROJECT_ROOT / "config" / "memory_source_ledger.json"),
    )
)

DEFAULT_CONFIG = {
    "schema_version": "memory-source-ledger-config-v0.1",
    "enabled": False,
    "inbox": "",
    "poll_interval_seconds": 60,
    "min_poll_interval_seconds": 10,
    "policy": {
        "explicit_inbox_only": True,
        "private_directory_scan": False,
        "candidate_created": False,
        "durable_memory_written": False,
        "autostart": False,
    },
}


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "y", "on", "ja"}:
        return True
    if lowered in {"0", "false", "no", "n", "off", "nein"}:
        return False
    raise ValueError("expected true/false")


def load_config() -> dict[str, Any]:
    data = dict(DEFAULT_CONFIG)

    if CONFIG_PATH.exists():
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        data.update(loaded)
        policy = dict(DEFAULT_CONFIG["policy"])
        policy.update(loaded.get("policy", {}))
        data["policy"] = policy

    return data


def configured_inbox(value: str | None = None) -> Path:
    if value:
        return Path(value).expanduser().resolve()

    config = load_config()
    configured = str(config.get("inbox") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    return default_import_inbox().resolve()


def configured_interval(value: int | None = None) -> int:
    config = load_config()
    interval = int(value if value is not None else config.get("poll_interval_seconds", 60))
    minimum = int(config.get("min_poll_interval_seconds", 10))

    if interval < minimum:
        raise SystemExit(f"ABORT interval must be >= {minimum} seconds")

    return interval



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



def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def ledger_dir() -> Path:
    base = managed_path("logs", env_var="MEMORIA_LOG_DIR", fallback_rel="logs")
    path = base / "source_ledger"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ledger_path() -> Path:
    return ledger_dir() / f"{today()}.jsonl"


def load_seen() -> set[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    for path in sorted(ledger_dir().glob("*.jsonl")):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                source_file = str(item.get("source_file", ""))
                source_sha256 = str(item.get("source_sha256", ""))
                if source_file and source_sha256:
                    seen.add((source_file, source_sha256))
        except Exception:
            continue
    return seen


def append_event(event: dict[str, Any]) -> None:
    path = ledger_path()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def scan_inbox(inbox: Path) -> dict[str, Any]:
    require_selected_storage_mounted()
    inbox = inbox.expanduser().resolve()

    if not inbox.exists():
        raise SystemExit(f"ABORT inbox does not exist: {inbox}")

    if not inbox.is_dir():
        raise SystemExit(f"ABORT inbox is not a directory: {inbox}")

    seen = load_seen()
    events: list[dict[str, Any]] = []

    for path in sorted(inbox.iterdir()):
        if not path.is_file():
            continue

        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue

        stat = path.stat()
        source_file = str(path.resolve())
        source_sha256 = sha256_file(path)
        key = (source_file, source_sha256)

        if key in seen:
            continue

        event = {
            "schema_version": "memory-source-ledger-v0.1",
            "seen_at": utc_now(),
            "source_file": source_file,
            "source_name": path.name,
            "source_sha256": source_sha256,
            "size_bytes": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat(),
            "status": "seen",
            "processed": False,
            "policy": {
                "explicit_inbox_only": True,
                "private_directory_scan": False,
                "candidate_created": False,
                "durable_memory_written": False,
            },
        }

        append_event(event)
        events.append(event)
        seen.add(key)

    return {
        "version": "memory-source-ledger-v0.1",
        "inbox": str(inbox),
        "ledger": str(ledger_path()),
        "new_events": len(events),
        "events": events,
    }


def print_result(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return

    print("MEMORIA MEMORY SOURCE LEDGER V0.1")
    print("-" * 48)
    print("Explicit inbox only. No private directory scan.")
    print("No candidates are created. No durable memory is written.")
    print(f"Inbox: {result['inbox']}")
    print(f"Ledger: {result['ledger']}")
    print(f"New files: {result['new_events']}")

    for event in result["events"]:
        print(f"- {event['source_name']} | {event['source_sha256'][:12]}... | {event['size_bytes']} bytes")



def command_config_show(args: argparse.Namespace) -> int:
    config = load_config()
    if args.json:
        print(json.dumps(config, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print("MEMORIA MEMORY SOURCE LEDGER CONFIG V0.1")
        print("-" * 48)
        print(f"Config: {CONFIG_PATH}")
        print(f"Enabled: {config.get('enabled')}")
        print(f"Inbox: {config.get('inbox')}")
        print(f"Poll interval seconds: {config.get('poll_interval_seconds')}")
        print(f"Min poll interval seconds: {config.get('min_poll_interval_seconds')}")
        print("Policy: explicit inbox only, no private directory scan, no candidates, no durable memory.")
    return 0


def command_config_set(args: argparse.Namespace) -> int:
    config = load_config()

    if args.enabled is not None:
        try:
            config["enabled"] = parse_bool(args.enabled)
        except ValueError as e:
            print(f"ABORT invalid --enabled: {e}")
            return 23

    if args.inbox:
        require_selected_storage_mounted()
        inbox = Path(args.inbox).expanduser().resolve()
        inbox.mkdir(parents=True, exist_ok=True)
        config["inbox"] = str(inbox)

    if args.interval is not None:
        minimum = int(config.get("min_poll_interval_seconds", 10))
        if args.interval < minimum:
            print(f"ABORT interval must be >= {minimum} seconds")
            return 23
        config["poll_interval_seconds"] = int(args.interval)

    policy = dict(config.get("policy", {}))
    policy["explicit_inbox_only"] = True
    policy["private_directory_scan"] = False
    policy["candidate_created"] = False
    policy["durable_memory_written"] = False
    policy["autostart"] = bool(policy.get("autostart", False))
    config["policy"] = policy

    save_config(config)

    print("OK Memory Source Ledger config updated")
    print(f"Enabled: {config.get('enabled')}")
    print(f"Inbox: {config.get('inbox')}")
    print(f"Poll interval seconds: {config.get('poll_interval_seconds')}")
    return 0


def command_scan(args: argparse.Namespace) -> int:
    result = scan_inbox(configured_inbox(args.inbox))
    print_result(result, args.json)
    return 0


def command_watch(args: argparse.Namespace) -> int:
    inbox = configured_inbox(args.inbox)
    interval = configured_interval(args.interval)

    print("MEMORIA MEMORY SOURCE LEDGER WATCH V0.1")
    print("-" * 48)
    print("Explicit inbox only. No private directory scan.")
    print("No candidates are created. No durable memory is written.")
    print(f"Inbox: {inbox.expanduser().resolve()}")
    print(f"Interval: {interval}s")
    print("Press Ctrl+C to stop.")
    print()

    try:
        while True:
            result = scan_inbox(inbox)
            if result["new_events"]:
                print_result(result, False)
                print()
            time.sleep(interval)
    except KeyboardInterrupt:
        print("OK source ledger watch stopped")
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MEMORIA explicit import inbox source ledger")
    sub = parser.add_subparsers(dest="command", required=True)

    config_cmd = sub.add_parser("config")
    config_sub = config_cmd.add_subparsers(dest="config_command", required=True)

    config_show = config_sub.add_parser("show")
    config_show.add_argument("--json", action="store_true")
    config_show.set_defaults(func=command_config_show)

    config_set = config_sub.add_parser("set")
    config_set.add_argument("--enabled", default=None)
    config_set.add_argument("--inbox", default="")
    config_set.add_argument("--interval", type=int, default=None)
    config_set.set_defaults(func=command_config_set)

    scan = sub.add_parser("scan")
    scan.add_argument("--inbox", default="")
    scan.add_argument("--json", action="store_true")
    scan.set_defaults(func=command_scan)

    watch = sub.add_parser("watch")
    watch.add_argument("--inbox", default="")
    watch.add_argument("--interval", type=int, default=None)
    watch.set_defaults(func=command_watch)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
