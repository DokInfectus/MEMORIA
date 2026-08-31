#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from memoria_storage_paths import managed_path

ROOT = Path(__file__).resolve().parents[1]

MEMORY_DIR = managed_path(
    "memory",
    env_var="MEMORIA_MEMORY_DIR",
    fallback_rel="knowledge/memory",
)

CANDIDATE_DIR = managed_path(
    "memory_candidates",
    env_var="MEMORIA_CANDIDATE_DIR",
    fallback_rel="knowledge/memory_candidates",
)

IMPORTS_DIR = managed_path(
    "imports",
    env_var="MEMORIA_IMPORTS_DIR",
    fallback_rel="imports",
)

SOURCE_LEDGER_CONFIG = ROOT / "config" / "memory_source_ledger.json"


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def json_files(path: Path, pattern: str) -> list[Path]:
    if not path.exists():
        return []
    return sorted(path.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)


def short(text: str, limit: int = 90) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def print_section(title: str) -> None:
    print()
    print(f"## {title}")
    print("-" * 60)


def show_memories() -> None:
    print_section("Durable Memories / MEM-*")
    files = json_files(MEMORY_DIR, "MEM-*.json")
    print(f"Path: {MEMORY_DIR}")
    print(f"Count: {len(files)}")

    for path in files[:10]:
        data = read_json(path)
        memory_id = data.get("id") or path.stem
        title = data.get("title") or short(data.get("text") or data.get("content") or "")
        layer = data.get("layer") or data.get("metadata", {}).get("layer") or "unknown"
        state = data.get("state") or data.get("status") or "active"
        print(f"- {memory_id} | {state} | {layer} | {short(title)}")

    if len(files) > 10:
        print(f"... {len(files) - 10} more")


def show_candidates() -> None:
    print_section("Memory Candidates / CAND-*")
    files = json_files(CANDIDATE_DIR, "CAND-*.json")
    print(f"Path: {CANDIDATE_DIR}")
    print(f"Count: {len(files)}")

    states: Counter[str] = Counter()
    for path in files:
        data = read_json(path)
        states[str(data.get("state") or "unknown")] += 1

    if states:
        print("States:")
        for state, count in sorted(states.items()):
            print(f"- {state}: {count}")

    print()
    print("Latest:")
    for path in files[:10]:
        data = read_json(path)
        candidate_id = data.get("id") or path.stem
        title = data.get("title") or short(data.get("text") or data.get("content") or "")
        state = data.get("state") or "unknown"
        layer = data.get("layer") or data.get("metadata", {}).get("layer") or "unknown"
        print(f"- {candidate_id} | {state} | {layer} | {short(title)}")

    if len(files) > 10:
        print(f"... {len(files) - 10} more")


def show_imports() -> None:
    print_section("Imports / Source Inbox")
    print(f"Path: {IMPORTS_DIR}")
    if IMPORTS_DIR.exists():
        files = sorted(
            [p for p in IMPORTS_DIR.rglob("*") if p.is_file()],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    else:
        files = []

    print(f"Files: {len(files)}")
    for path in files[:10]:
        try:
            size = path.stat().st_size
        except Exception:
            size = 0
        print(f"- {path.relative_to(IMPORTS_DIR)} | {size} bytes")

    if len(files) > 10:
        print(f"... {len(files) - 10} more")

    config = read_json(SOURCE_LEDGER_CONFIG)
    if config:
        print()
        print("Source Ledger:")
        print(f"- enabled: {config.get('enabled')}")
        print(f"- inbox: {config.get('inbox')}")
        print(f"- poll_interval_seconds: {config.get('poll_interval_seconds')}")


def show_policy() -> None:
    print_section("Policy")
    print("- Read-only overview. No config changes.")
    print("- No candidate approval/reject/archive is performed here.")
    print("- No durable memory promotion is performed here.")
    print("- No source/import file is deleted here.")
    print("- Durable memory changes require explicit review/promotion tools.")
    print("- Future power-user auto-promotion must be explicit opt-in and guarded.")


def main() -> int:
    print("MEMORIA MEMORY OVERVIEW V0.1")
    print("-" * 60)
    print("Read-only memory/candidate/import overview. No writes. No deletes.")

    show_memories()
    show_candidates()
    show_imports()
    show_policy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
