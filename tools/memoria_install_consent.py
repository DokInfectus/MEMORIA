#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from getpass import getuser

ROOT = Path(__file__).resolve().parents[1]
TERMS_PATH = ROOT / "docs" / "MEMORIA_LOCAL_TERMS.md"
CONSENT_PATH = ROOT / "config" / "install_consent.json"
EXAMPLE_PATH = ROOT / "config" / "install_consent.example.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_terms() -> str:
    if not TERMS_PATH.exists():
        raise SystemExit(f"ABORT: terms file missing: {TERMS_PATH}")
    return TERMS_PATH.read_text(encoding="utf-8")


def consent_payload(accepted_by: str | None = None) -> dict:
    return {
        "schema_version": "memoria-install-consent-v0.1",
        "accepted": True,
        "accepted_at": now_iso(),
        "accepted_by": accepted_by or getuser(),
        "terms_document": "docs/MEMORIA_LOCAL_TERMS.md",
        "local_read_write_allowed": True,
        "third_party_upload_allowed": False,
        "hidden_telemetry_allowed": False,
        "private_directory_scan_allowed_without_explicit_path": False,
        "candidate_creation_allowed_by_policy": True,
        "durable_memory_requires_approval_or_explicit_policy": True,
    }


def command_show(_args: argparse.Namespace) -> int:
    print(load_terms())
    return 0


def command_status(_args: argparse.Namespace) -> int:
    if not CONSENT_PATH.exists():
        print("Install consent: MISSING")
        return 1

    data = json.loads(CONSENT_PATH.read_text(encoding="utf-8"))
    if data.get("accepted") is True:
        print("Install consent: ACCEPTED")
        print(f"Accepted at: {data.get('accepted_at')}")
        print(f"Accepted by: {data.get('accepted_by')}")
        return 0

    print("Install consent: NOT ACCEPTED")
    return 1


def command_accept(args: argparse.Namespace) -> int:
    if not args.yes:
        print(load_terms())
        print()
        answer = input('Type ACCEPT to continue installation: ').strip()
        if answer != "ACCEPT":
            print("ABORT: local data terms not accepted")
            return 2

    CONSENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = consent_payload(args.accepted_by)
    CONSENT_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"OK install consent accepted: {CONSENT_PATH}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MEMORIA install consent gate")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="Show MEMORIA local data terms")
    show.set_defaults(func=command_show)

    status = sub.add_parser("status", help="Check whether install consent is accepted")
    status.set_defaults(func=command_status)

    accept = sub.add_parser("accept", help="Accept MEMORIA local data terms")
    accept.add_argument("--yes", action="store_true", help="Non-interactive accept for scripted installer flows")
    accept.add_argument("--accepted-by", default=None)
    accept.set_defaults(func=command_accept)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
