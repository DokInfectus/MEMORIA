#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(
    os.environ.get(
        "MEMORIA_RUNTIME_MODE_CONFIG",
        str(ROOT / "config" / "runtime_mode.json"),
    )
)

VALID_MODES = {
    "NORMAL": {
        "retrieval_enabled": True,
        "candidate_creation_enabled": True,
        "promotion_enabled": True,
        "durable_writes_enabled": True,
        "attachment_writes_enabled": True,
        "background_processing_enabled": True,
        "description": "Normal MEMORIA operation.",
    },
    "THINKING_MODE": {
        "retrieval_enabled": True,
        "candidate_creation_enabled": False,
        "promotion_enabled": False,
        "durable_writes_enabled": False,
        "attachment_writes_enabled": False,
        "background_processing_enabled": False,
        "description": "Use existing approved knowledge only. Do not store anything new.",
    },
    "SERVICE_STOP": {
        "retrieval_enabled": False,
        "candidate_creation_enabled": False,
        "promotion_enabled": False,
        "durable_writes_enabled": False,
        "attachment_writes_enabled": False,
        "background_processing_enabled": False,
        "description": "MEMORIA processing is stopped or paused. No writes.",
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_mode(value: str) -> str:
    mode = value.strip().upper().replace("-", "_").replace(" ", "_")

    aliases = {
        "THINKING": "THINKING_MODE",
        "THINKINGMODE": "THINKING_MODE",
        "SERVICE": "SERVICE_STOP",
        "STOP": "SERVICE_STOP",
        "SERVICESTOP": "SERVICE_STOP",
        "RUN_STOP": "SERVICE_STOP",
    }

    mode = aliases.get(mode, mode)

    if mode not in VALID_MODES:
        raise ValueError(f"invalid runtime mode: {value}")

    return mode


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {
            "schema_version": "runtime-mode-v0.1",
            "runtime_mode": "NORMAL",
            "updated_by": "default",
            "reason": "Runtime mode config missing; using NORMAL default.",
            "config_exists": False,
        }

    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    mode = normalize_mode(str(data.get("runtime_mode", "NORMAL")))
    data["runtime_mode"] = mode
    data["config_exists"] = True
    return data


def mode_status() -> dict[str, Any]:
    config = load_config()
    mode = normalize_mode(config["runtime_mode"])
    policy = VALID_MODES[mode]

    return {
        "schema_version": "runtime-mode-status-v0.1",
        "config_path": str(CONFIG_PATH),
        "runtime_mode": mode,
        "policy": policy,
        "config": config,
    }


def save_mode(mode: str, reason: str, updated_by: str = "memoria_runtime_mode.py") -> dict[str, Any]:
    normalized = normalize_mode(mode)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "schema_version": "runtime-mode-v0.1",
        "runtime_mode": normalized,
        "updated_at": now_iso(),
        "updated_by": updated_by,
        "reason": reason,
    }

    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return mode_status()


def print_status(as_json: bool = False) -> int:
    status = mode_status()

    if as_json:
        print(json.dumps(status, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    policy = status["policy"]

    print("## MEMORIA RUNTIME MODE V0.1")
    print("------------------------------------------------------------")
    print(f"Mode: {status['runtime_mode']}")
    print(f"Config: {status['config_path']}")
    print(f"Description: {policy['description']}")
    print()
    print(f"Retrieval enabled: {'yes' if policy['retrieval_enabled'] else 'no'}")
    print(f"Candidate creation enabled: {'yes' if policy['candidate_creation_enabled'] else 'no'}")
    print(f"Promotion enabled: {'yes' if policy['promotion_enabled'] else 'no'}")
    print(f"Durable writes enabled: {'yes' if policy['durable_writes_enabled'] else 'no'}")
    print(f"Attachment writes enabled: {'yes' if policy['attachment_writes_enabled'] else 'no'}")
    print(f"Background processing enabled: {'yes' if policy['background_processing_enabled'] else 'no'}")
    return 0


def command_set(args: argparse.Namespace) -> int:
    status = save_mode(args.mode, args.reason or "Explicit runtime mode change.")
    print(f"OK runtime mode set to {status['runtime_mode']}")
    print_status(as_json=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MEMORIA runtime mode control")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=lambda args: print_status(args.json))

    set_mode = sub.add_parser("set")
    set_mode.add_argument("mode", help="NORMAL, THINKING_MODE, or SERVICE_STOP")
    set_mode.add_argument("--reason", default="")
    set_mode.set_defaults(func=command_set)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
