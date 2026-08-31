#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = Path(
    os.environ.get(
        "MEMORIA_MEMORY_AUTO_POLICY",
        str(ROOT / "config" / "memory_auto_policy.json"),
    )
)

DEFAULT_POLICY = {
    "enabled": True,
    "create_candidates": True,
    "allowed_categories": ["project", "persona", "preference", "custom-important", "hardware"],
    "never_store_categories": ["sensitive", "smalltalk", "low-signal", "noise"],
    "auto_approve_categories": [],
    "allow_durable_auto_promote": False,
    "auto_promote_categories": [],
}


def load_policy() -> dict[str, Any]:
    if not POLICY_PATH.exists():
        return dict(DEFAULT_POLICY)

    data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    policy = dict(DEFAULT_POLICY)
    policy.update(data)
    return policy


def run_command(command: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
    )
    return result.returncode, result.stdout


def run_intake(text: str, create_candidate: bool = False) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "tools" / "memoria_memory_intake.py"),
        "analyze",
        "--text",
        text,
        "--json",
    ]

    if create_candidate:
        command.append("--create-candidate")

    code, output = run_command(command)
    if code != 0:
        raise RuntimeError(output)

    return json.loads(output)


def category_allowed(category: str, policy: dict[str, Any]) -> bool:
    never = set(policy.get("never_store_categories", []))
    allowed = set(policy.get("allowed_categories", []))

    if category in never:
        return False

    if allowed and category not in allowed:
        return False

    return True


def can_create_candidate(result: dict[str, Any], policy: dict[str, Any]) -> tuple[bool, str]:
    decision = result.get("decision", {})
    category = decision.get("category", "")

    if not policy.get("enabled", False):
        return False, "policy disabled"

    if not policy.get("create_candidates", False):
        return False, "candidate creation disabled by policy"

    if decision.get("action") != "create-candidate":
        return False, f"decision action is {decision.get('action')}"

    if result.get("safety_warnings"):
        return False, "safety warnings present"

    if result.get("duplicate", {}).get("duplicate"):
        return False, f"duplicate detected: {result.get('duplicate', {}).get('id')}"

    if not category_allowed(category, policy):
        return False, f"category not allowed by policy: {category}"

    return True, "eligible"


def set_candidate_state(candidate_id: str, action: str) -> dict[str, Any]:
    code, output = run_command([
        sys.executable,
        str(ROOT / "tools" / "memoria_memory_candidate_store.py"),
        action,
        candidate_id,
    ])
    return {
        "action": action,
        "exit_code": code,
        "output": output,
        "ok": code == 0,
    }


def promote_candidate(candidate_id: str) -> dict[str, Any]:
    code, output = run_command([
        sys.executable,
        str(ROOT / "tools" / "memoria_memory_promote.py"),
        "promote",
        candidate_id,
    ])
    return {
        "action": "promote",
        "exit_code": code,
        "output": output,
        "ok": code == 0,
    }


def process_text(text: str) -> dict[str, Any]:
    policy = load_policy()
    dry = run_intake(text, create_candidate=False)

    allowed, reason = can_create_candidate(dry, policy)

    result: dict[str, Any] = {
        "version": "memory-auto-policy-v0.1",
        "policy": policy,
        "dry_run": dry,
        "auto": {
            "candidate_requested": False,
            "candidate_created": False,
            "candidate_id": None,
            "candidate_reason": reason,
            "approved": False,
            "promoted": False,
            "durable_memory_written": False,
            "actions": [],
        },
    }

    if not allowed:
        return result

    created = run_intake(text, create_candidate=True)
    creation = created.get("candidate_creation", {})
    candidate_id = creation.get("candidate_id")

    result["auto"]["candidate_requested"] = True
    result["auto"]["candidate_created"] = bool(creation.get("created"))
    result["auto"]["candidate_id"] = candidate_id
    result["auto"]["candidate_reason"] = creation.get("reason", "candidate creation attempted")

    if not candidate_id:
        return result

    category = dry.get("decision", {}).get("category", "")
    auto_approve = set(policy.get("auto_approve_categories", []))
    auto_promote = set(policy.get("auto_promote_categories", []))
    allow_promote = bool(policy.get("allow_durable_auto_promote", False))

    if category in auto_approve or (allow_promote and category in auto_promote):
        state_result = set_candidate_state(candidate_id, "approve")
        result["auto"]["actions"].append(state_result)
        result["auto"]["approved"] = state_result["ok"]

    if allow_promote and category in auto_promote:
        promote_result = promote_candidate(candidate_id)
        result["auto"]["actions"].append(promote_result)
        result["auto"]["promoted"] = promote_result["ok"]
        result["auto"]["durable_memory_written"] = promote_result["ok"]

    return result


def print_policy() -> int:
    print("## MEMORIA MEMORY AUTO POLICY V0.1")
    print("------------------------------------------------------------")
    print(f"Policy file: {POLICY_PATH}")
    print(json.dumps(load_policy(), indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def command_process(args: argparse.Namespace) -> int:
    text = args.text or ""

    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")

    result = process_text(text)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    decision = result["dry_run"]["decision"]
    auto = result["auto"]

    print("## MEMORIA MEMORY AUTO POLICY PROCESS V0.1")
    print("------------------------------------------------------------")
    print("Only explicit input text is processed.")
    print("No private chat logs are scanned.")
    print()
    print(f"Decision: {decision.get('action')}")
    print(f"Category: {decision.get('category')}")
    print(f"Layer: {decision.get('layer')}")
    print(f"Reason: {decision.get('reason')}")
    print(f"Duplicate: {'yes' if result['dry_run']['duplicate'].get('duplicate') else 'no'}")
    print()
    print(f"Candidate Created: {'yes' if auto['candidate_created'] else 'no'}")
    if auto.get("candidate_id"):
        print(f"Candidate ID: {auto['candidate_id']}")
    print(f"Candidate Reason: {auto['candidate_reason']}")
    print(f"Auto Approved: {'yes' if auto['approved'] else 'no'}")
    print(f"Durable Memory Written: {'yes' if auto['durable_memory_written'] else 'no'}")
    print()
    print("Filtered Text:")
    print(result["dry_run"].get("cleaned_text", ""))

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MEMORIA memory auto policy processor")
    sub = parser.add_subparsers(dest="command", required=True)

    policy = sub.add_parser("policy")
    policy.set_defaults(func=lambda _args: print_policy())

    process = sub.add_parser("process")
    process.add_argument("--text", default="")
    process.add_argument("--text-file")
    process.add_argument("--json", action="store_true")
    process.set_defaults(func=command_process)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
