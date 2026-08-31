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
        "MEMORIA_LANGUAGE_CONFIG",
        str(PROJECT_ROOT / "config" / "language.json"),
    )
)

SUPPORTED_LANGUAGES = {
    "de": {
        "name": "Deutsch",
        "description": "German workshop/development language",
    },
    "en": {
        "name": "English",
        "description": "Public/default project language",
    },
}

DEFAULT_LANGUAGE = "en"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_config() -> dict[str, Any]:
    return {
        "schema_version": "memoria-language-config-v0.1",
        "language": DEFAULT_LANGUAGE,
        "supported_languages": list(SUPPORTED_LANGUAGES.keys()),
        "policy": {
            "installer_must_ask_first_run": True,
            "public_docs_default": "en",
            "dev_workshop_language": "de",
            "no_private_content_translation": True,
        },
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return default_config()

    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    merged = default_config()
    merged.update(data)

    policy = dict(default_config()["policy"])
    policy.update(data.get("policy", {}))
    merged["policy"] = policy
    merged["supported_languages"] = list(SUPPORTED_LANGUAGES.keys())

    return merged


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(config, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(CONFIG_PATH)


def normalize_language(value: str) -> str:
    normalized = value.strip().lower()

    aliases = {
        "deutsch": "de",
        "german": "de",
        "ger": "de",
        "english": "en",
        "englisch": "en",
        "eng": "en",
    }

    normalized = aliases.get(normalized, normalized)

    if normalized not in SUPPORTED_LANGUAGES:
        raise SystemExit(
            "ABORT unsupported language. Supported: "
            + ", ".join(sorted(SUPPORTED_LANGUAGES))
        )

    return normalized


def print_config(config: dict[str, Any]) -> None:
    lang = normalize_language(str(config.get("language", DEFAULT_LANGUAGE)))
    info = SUPPORTED_LANGUAGES[lang]

    print("MEMORIA LANGUAGE CONFIG V0.1")
    print("-" * 48)
    print(f"Config: {CONFIG_PATH}")
    print(f"Language: {lang} ({info['name']})")
    print()
    print("Supported:")
    for key, value in SUPPORTED_LANGUAGES.items():
        marker = "*" if key == lang else "-"
        print(f"{marker} {key}: {value['name']} - {value['description']}")
    print()
    print("Policy:")
    policy = config.get("policy", {})
    for key in sorted(policy):
        print(f"- {key}: {policy[key]}")


def command_show(args: argparse.Namespace) -> int:
    config = load_config()

    if args.json:
        print(json.dumps(config, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print_config(config)

    return 0


def command_set(args: argparse.Namespace) -> int:
    config = load_config()
    language = normalize_language(args.language)

    config["language"] = language
    config["supported_languages"] = list(SUPPORTED_LANGUAGES.keys())
    config["updated_at"] = utc_now()

    if "created_at" not in config:
        config["created_at"] = utc_now()

    policy = dict(config.get("policy", {}))
    policy["installer_must_ask_first_run"] = True
    policy["public_docs_default"] = "en"
    policy["dev_workshop_language"] = "de"
    policy["no_private_content_translation"] = True
    config["policy"] = policy

    save_config(config)

    print("OK MEMORIA language config updated")
    print_config(config)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MEMORIA language configuration")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=command_show)

    set_cmd = sub.add_parser("set")
    set_cmd.add_argument("language")
    set_cmd.set_defaults(func=command_set)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
