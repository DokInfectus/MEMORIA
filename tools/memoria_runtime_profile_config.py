#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from configure.prompt_profiles import get_prompt_profile_options, validate_prompt_profile
from configure.profiles import list_profiles, describe_profile, get_profile_settings


CONFIG_PATH = Path(
    os.environ.get(
        "MEMORIA_RUNTIME_CONFIG",
        str(PROJECT_ROOT / "config" / "runtime.json"),
    )
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"ABORT runtime config not found: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    backup = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".bak-runtime-profile-config-v01")
    if CONFIG_PATH.exists() and not backup.exists():
        backup.write_text(CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    tmp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
    tmp.write_text(
        json.dumps(config, indent=4, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(CONFIG_PATH)


def validate_budget(config: dict[str, Any]) -> None:
    context = int(config.get("context_length", 0) or 0)
    planned = (
        int(config.get("max_tokens", 0) or 0)
        + int(config.get("memory_token_budget", 0) or 0)
        + int(config.get("history_token_budget", 0) or 0)
        + int(config.get("reserved_output_tokens", 0) or 0)
    )

    if context <= 0:
        raise SystemExit("ABORT context_length must be positive")

    if planned > context:
        raise SystemExit(
            "ABORT token budgets exceed context_length: "
            f"planned={planned}, context_length={context}"
        )


def print_config(config: dict[str, Any]) -> None:
    print("MEMORIA RUNTIME PROFILE CONFIG V0.1")
    print("-" * 48)
    print(f"Config: {CONFIG_PATH}")
    print()
    print(f"profile: {config.get('profile', '')}")
    print(f"prompt_profile: {config.get('prompt_profile', '')}")
    print(f"model: {config.get('model', '')}")
    print(f"adapter: {config.get('adapter', '')}")
    print()
    print(f"context_length: {config.get('context_length', '')}")
    print(f"max_tokens: {config.get('max_tokens', '')}")
    print(f"memory_token_budget: {config.get('memory_token_budget', '')}")
    print(f"history_token_budget: {config.get('history_token_budget', '')}")
    print(f"reserved_output_tokens: {config.get('reserved_output_tokens', '')}")
    print()
    print("Prompt profiles:")
    for item in get_prompt_profile_options():
        marker = "*" if item.key == config.get("prompt_profile") else "-"
        print(f"{marker} {item.key}: {item.label} - {item.description}")
    print()
    print("Configuration profiles:")
    for profile in list_profiles():
        marker = "*" if profile == config.get("profile") else "-"
        print(f"{marker} {profile}: {describe_profile(profile)}")


def command_show(args: argparse.Namespace) -> int:
    config = load_config()
    if args.json:
        print(json.dumps(config, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print_config(config)
    return 0


def command_set_prompt(args: argparse.Namespace) -> int:
    config = load_config()

    try:
        prompt_profile = validate_prompt_profile(args.prompt_profile)
    except ValueError as e:
        raise SystemExit(f"ABORT {e}") from e

    config["prompt_profile"] = prompt_profile
    config["updated_at"] = utc_now()
    save_config(config)

    print("OK runtime prompt profile updated")
    print_config(config)
    return 0


def command_set_profile(args: argparse.Namespace) -> int:
    config = load_config()
    profile = args.profile.strip()

    if profile not in list_profiles():
        raise SystemExit("ABORT unsupported configuration profile: " + profile)

    config["profile"] = profile

    if args.apply_token_budgets:
        settings = get_profile_settings(profile)
        for key, value in settings.items():
            config[key] = value
        validate_budget(config)

    config["updated_at"] = utc_now()
    save_config(config)

    print("OK runtime configuration profile updated")
    print_config(config)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Edit MEMORIA runtime profile settings safely.")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=command_show)

    set_prompt = sub.add_parser("set-prompt")
    set_prompt.add_argument("prompt_profile")
    set_prompt.set_defaults(func=command_set_prompt)

    set_profile = sub.add_parser("set-profile")
    set_profile.add_argument("profile")
    set_profile.add_argument("--apply-token-budgets", action="store_true")
    set_profile.set_defaults(func=command_set_profile)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
