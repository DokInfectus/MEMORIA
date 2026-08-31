#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from memoria_runtime_mode import mode_status  # noqa: E402


CAPABILITY_LABELS = {
    "retrieval_enabled": "retrieval",
    "candidate_creation_enabled": "candidate creation",
    "promotion_enabled": "promotion",
    "durable_writes_enabled": "durable memory writes",
    "attachment_writes_enabled": "attachment storage writes",
    "background_processing_enabled": "background processing",
}


def guard_check(capability: str) -> dict:
    status = mode_status()
    policy = status["policy"]

    if capability not in CAPABILITY_LABELS:
        return {
            "allowed": False,
            "runtime_mode": status["runtime_mode"],
            "capability": capability,
            "reason": f"unknown capability: {capability}",
        }

    allowed = bool(policy.get(capability, False))

    return {
        "allowed": allowed,
        "runtime_mode": status["runtime_mode"],
        "capability": capability,
        "label": CAPABILITY_LABELS[capability],
        "reason": "allowed by runtime mode" if allowed else "blocked by runtime mode",
    }


def require_capability(capability: str) -> None:
    result = guard_check(capability)
    if result["allowed"]:
        return

    print("BLOCKED by MEMORIA runtime mode")
    print(f"Mode: {result['runtime_mode']}")
    print(f"Capability: {result['capability']}")
    print(f"Reason: {result['reason']}")
    raise SystemExit(23)


def command_check(args: argparse.Namespace) -> int:
    result = guard_check(args.capability)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return 0 if result["allowed"] else 23

    print("## MEMORIA RUNTIME GUARD V0.1")
    print("------------------------------------------------------------")
    print(f"Mode: {result['runtime_mode']}")
    print(f"Capability: {result['capability']}")
    print(f"Allowed: {'yes' if result['allowed'] else 'no'}")
    print(f"Reason: {result['reason']}")

    return 0 if result["allowed"] else 23


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MEMORIA runtime guard")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check")
    check.add_argument("capability", choices=sorted(CAPABILITY_LABELS))
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=command_check)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
