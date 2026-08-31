#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(
    os.environ.get(
        "MEMORIA_RUNTIME_CONFIG",
        str(PROJECT_ROOT / "config" / "runtime.json"),
    )
)

TOKEN_FIELDS = {
    "context_length": (1024, 1000000),
    "max_tokens": (1, 1000000),
    "memory_token_budget": (0, 1000000),
    "history_token_budget": (0, 1000000),
    "reserved_output_tokens": (1, 1000000),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"ABORT runtime config not found: {CONFIG_PATH}")

    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    backup = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".bak-runtime-config-editor-v01")
    if CONFIG_PATH.exists() and not backup.exists():
        backup.write_text(CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    tmp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(config, indent=4, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def parse_optional_int(value: str | None, field: str) -> int | None:
    if value is None:
        return None

    try:
        parsed = int(str(value).strip())
    except ValueError:
        raise SystemExit(f"ABORT {field} must be an integer")

    minimum, maximum = TOKEN_FIELDS[field]
    if parsed < minimum or parsed > maximum:
        raise SystemExit(f"ABORT {field} must be between {minimum} and {maximum}")

    return parsed


def validate_budget(config: dict[str, Any]) -> None:
    context = int(config.get("context_length", 0))
    max_tokens = int(config.get("max_tokens", 0))
    memory = int(config.get("memory_token_budget", 0))
    history = int(config.get("history_token_budget", 0))
    reserved = int(config.get("reserved_output_tokens", 0))

    if context <= 0:
        raise SystemExit("ABORT context_length must be positive")

    planned = max_tokens + memory + history + reserved
    if planned > context:
        raise SystemExit(
            "ABORT token budgets exceed context_length: "
            f"max_tokens({max_tokens}) + memory({memory}) + "
            f"history({history}) + reserved({reserved}) = {planned}, "
            f"context_length={context}"
        )


def print_config(config: dict[str, Any]) -> None:
    print("MEMORIA RUNTIME CONFIG EDITOR V0.1")
    print("-" * 48)
    print(f"Config: {CONFIG_PATH}")
    print()
    for key in [
        "setup_mode",
        "adapter",
        "base_url",
        "model",
        "prompt_profile",
        "profile",
        "context_length",
        "max_tokens",
        "memory_token_budget",
        "history_token_budget",
        "reserved_output_tokens",
    ]:
        if key in config:
            print(f"{key}: {config[key]}")

    context = int(config.get("context_length", 0))
    planned = sum(int(config.get(key, 0)) for key in [
        "max_tokens",
        "memory_token_budget",
        "history_token_budget",
        "reserved_output_tokens",
    ])
    print()
    print(f"planned_token_budget_sum: {planned}")
    print(f"context_remaining_after_planned: {context - planned}")


def command_show(args: argparse.Namespace) -> int:
    config = load_config()
    if args.json:
        print(json.dumps(config, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print_config(config)
    return 0


def command_set(args: argparse.Namespace) -> int:
    config = load_config()

    updates = {
        "context_length": parse_optional_int(args.context_length, "context_length"),
        "max_tokens": parse_optional_int(args.max_tokens, "max_tokens"),
        "memory_token_budget": parse_optional_int(args.memory_token_budget, "memory_token_budget"),
        "history_token_budget": parse_optional_int(args.history_token_budget, "history_token_budget"),
        "reserved_output_tokens": parse_optional_int(args.reserved_output_tokens, "reserved_output_tokens"),
    }

    changed = False
    for key, value in updates.items():
        if value is not None:
            config[key] = value
            changed = True

    if not changed:
        print("INFO no runtime config changes requested")
        return 0

    # Manual token budget edits mean the active configuration no longer
    # represents a named preset. Mark it as custom so CLI/Matrix UI stay honest.
    config["profile"] = "custom"
    validate_budget(config)
    config["updated_at"] = utc_now()

    save_config(config)

    print("OK runtime config updated")
    print_config(config)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Edit MEMORIA runtime token budgets safely.")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=command_show)

    set_cmd = sub.add_parser("set")
    set_cmd.add_argument("--context-length", default=None)
    set_cmd.add_argument("--max-tokens", default=None)
    set_cmd.add_argument("--memory-token-budget", default=None)
    set_cmd.add_argument("--history-token-budget", default=None)
    set_cmd.add_argument("--reserved-output-tokens", default=None)
    set_cmd.set_defaults(func=command_set)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
