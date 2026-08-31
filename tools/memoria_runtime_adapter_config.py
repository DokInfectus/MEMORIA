#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from adapter.factory import supported_adapters


CONFIG_PATH = Path(
    os.environ.get(
        "MEMORIA_RUNTIME_CONFIG",
        str(PROJECT_ROOT / "config" / "runtime.json"),
    )
)

SETUP_MODE_BY_ADAPTER = {
    "LlamaCppAdapter": "llama-cpp-direct",
    "OpenWebUIAdapter": "open-webui",
    "OllamaAdapter": "ollama",
    "MockAdapter": "mock",
}

DEFAULT_BASE_URL_BY_ADAPTER = {
    "LlamaCppAdapter": "http://127.0.0.1:3000",
    "OpenWebUIAdapter": "http://127.0.0.1:8080",
    "OllamaAdapter": "http://127.0.0.1:11434",
    "MockAdapter": "",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"ABORT runtime config not found: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    backup = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".bak-runtime-adapter-config-v01")
    if CONFIG_PATH.exists() and not backup.exists():
        backup.write_text(CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    tmp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
    tmp.write_text(
        json.dumps(config, indent=4, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(CONFIG_PATH)


def validate_adapter(value: str) -> str:
    adapter = value.strip()
    if adapter not in supported_adapters():
        raise SystemExit(
            "ABORT unsupported adapter. Supported adapters: "
            + ", ".join(supported_adapters())
        )
    return adapter


def validate_base_url(value: str) -> str:
    text = value.strip()

    if not text:
        return ""

    parsed = urlparse(text)

    if parsed.scheme not in {"http", "https"}:
        raise SystemExit("ABORT base_url must start with http:// or https://")

    if not parsed.netloc:
        raise SystemExit("ABORT base_url must include host/port")

    if any(secret_word in text.lower() for secret_word in ["token", "api_key", "apikey", "password", "secret"]):
        raise SystemExit("ABORT base_url must not contain secrets")

    return text.rstrip("/")


def validate_text(value: str, field: str) -> str:
    text = value.strip()

    if not text:
        raise SystemExit(f"ABORT {field} must not be empty")

    if any(secret_word in text.lower() for secret_word in ["sk-", "api_key", "apikey", "password", "secret"]):
        raise SystemExit(f"ABORT {field} must not contain secrets")

    return text


def print_config(config: dict[str, Any]) -> None:
    print("MEMORIA RUNTIME ADAPTER CONFIG V0.1")
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
    ]:
        print(f"{key}: {config.get(key, '')}")
    print()
    print("Supported adapters:")
    for adapter in supported_adapters():
        marker = "*" if adapter == config.get("adapter") else "-"
        default_url = DEFAULT_BASE_URL_BY_ADAPTER.get(adapter, "")
        print(f"{marker} {adapter} default_base_url={default_url}")


def command_show(args: argparse.Namespace) -> int:
    config = load_config()
    if args.json:
        print(json.dumps(config, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print_config(config)
    return 0


def command_set(args: argparse.Namespace) -> int:
    config = load_config()
    changed = False

    if args.adapter:
        adapter = validate_adapter(args.adapter)
        config["adapter"] = adapter
        config["setup_mode"] = SETUP_MODE_BY_ADAPTER.get(adapter, config.get("setup_mode", "manual"))
        default_url = DEFAULT_BASE_URL_BY_ADAPTER.get(adapter, "")

        if default_url and not args.base_url:
            config["base_url"] = default_url

        changed = True

    if args.setup_mode:
        config["setup_mode"] = validate_text(args.setup_mode, "setup_mode")
        changed = True

    if args.base_url is not None:
        config["base_url"] = validate_base_url(args.base_url)
        changed = True

    if args.model:
        config["model"] = validate_text(args.model, "model")
        changed = True

    if not changed:
        print("INFO no adapter config changes requested")
        return 0

    config["updated_at"] = utc_now()
    save_config(config)

    print("OK runtime adapter config updated")
    print_config(config)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Edit MEMORIA runtime adapter settings safely.")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=command_show)

    set_cmd = sub.add_parser("set")
    set_cmd.add_argument("--adapter", default="")
    set_cmd.add_argument("--setup-mode", default="")
    set_cmd.add_argument("--base-url", default=None)
    set_cmd.add_argument("--model", default="")
    set_cmd.set_defaults(func=command_set)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
