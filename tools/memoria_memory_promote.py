#!/usr/bin/env python3
from __future__ import annotations

# MEMORIA storage watchdog: hard-stop enforcement.
from memoria_memory_storage_watchdog import build_status as _memoria_watchdog_status


def _memoria_require_storage_watchdog_ok():
    status = _memoria_watchdog_status()
    hard_stop = status.get("hard_stop", {})

    if hard_stop.get("active"):
        print("BLOCKED by Memory Storage Watchdog")
        print(f"Reason: {hard_stop.get('reason')}")
        print(hard_stop.get("message", "Storage hard stop active."))
        raise SystemExit(24)


import argparse
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from memoria_storage_paths import managed_path as _memoria_managed_path

ROOT = Path(__file__).resolve().parents[1]

CANDIDATE_DIR = _memoria_managed_path(
    "memory_candidates",
    "MEMORIA_CANDIDATE_DIR",
    "knowledge/memory_candidates",
)

MEMORY_DIR = _memoria_managed_path(
    "memory",
    "MEMORIA_MEMORY_DIR",
    "knowledge/memory",
)

MEMORY_VERSION = "0.1.0-memory-store"


def now_iso() -> str:
    return datetime.now().isoformat()


def memory_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"MEM-{stamp}-{suffix}"


def candidate_path(candidate_id: str) -> Path:
    candidate_ref = str(candidate_id or "").strip()

    if len(candidate_ref) < 5:
        raise ValueError("candidate id/suffix must be at least 5 characters")

    if re.fullmatch(r"CAND-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}", candidate_ref):
        return CANDIDATE_DIR / f"{candidate_ref}.json"

    matches = sorted(CANDIDATE_DIR.glob(f"CAND-*{candidate_ref}.json"))

    if not matches:
        raise FileNotFoundError(candidate_ref)

    if len(matches) > 1:
        ids = ", ".join(path.stem for path in matches[:10])
        raise ValueError(f"candidate suffix is not unique: {candidate_ref}; matches: {ids}")

    return matches[0]


def memory_path(mem_id: str) -> Path:
    if not re.fullmatch(r"MEM-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}", mem_id):
        raise ValueError("invalid memory id")
    return MEMORY_DIR / f"{mem_id}.json"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def normalize_tags(tags: list[str], layer: str, candidate_id: str) -> list[str]:
    result: list[str] = []

    def add(tag: str) -> None:
        clean = str(tag).strip().lower()
        clean = re.sub(r"[^a-z0-9_.:-]+", "-", clean)
        clean = clean.strip("-")
        if clean and clean not in result:
            result.append(clean)

    for tag in tags:
        add(tag)

    add("user-approved")
    add(f"layer:{layer}")
    add("source:candidate")
    add(f"candidate:{candidate_id}")

    return result[:40]


def build_memory(candidate: dict) -> dict:
    cand_id = candidate["id"]
    layer = candidate.get("layer", "user")
    created = now_iso()
    mem_id = memory_id()

    return {
        "version": MEMORY_VERSION,
        "id": mem_id,
        "status": "active",
        "category": "memory",
        "title": candidate.get("title", "").strip(),
        "content": candidate.get("text", "").strip(),
        "tags": normalize_tags(candidate.get("tags", []), layer, cand_id),
        "source_session": f"candidate:{cand_id}",
        "created": created,
        "updated": created,
    }


def validate_candidate(candidate: dict) -> None:
    if candidate.get("schema_version") != "memory-candidate-v0.1":
        raise ValueError("unsupported candidate schema")

    if candidate.get("state") != "user-approved":
        raise ValueError("candidate is not user-approved")

    if not candidate.get("title", "").strip():
        raise ValueError("candidate title is empty")

    if not candidate.get("text", "").strip():
        raise ValueError("candidate text is empty")

    safety = candidate.get("safety", {})
    if safety.get("sensitive_scan") != "passed":
        raise ValueError("candidate safety scan did not pass")

    if safety.get("warnings"):
        raise ValueError("candidate has safety warnings")


def promote(candidate_id: str, keep_candidate_state: bool = False) -> dict:
    cpath = candidate_path(candidate_id)
    if not cpath.exists():
        raise FileNotFoundError(candidate_id)

    candidate = read_json(cpath)
    validate_candidate(candidate)

    if candidate.get("promoted_to"):
        raise ValueError(f"candidate already promoted to {candidate.get('promoted_to')}")

    memory = build_memory(candidate)
    mpath = memory_path(memory["id"])

    write_json_atomic(mpath, memory)

    candidate["promoted_to"] = memory["id"]
    candidate["promoted_at"] = now_iso()
    candidate["updated_at"] = now_iso()

    if not keep_candidate_state:
        candidate["state"] = "archived"

    write_json_atomic(cpath, candidate)

    return {
        "candidate": candidate,
        "memory": memory,
        "memory_path": str(mpath),
        "candidate_path": str(cpath),
    }


def command_promote(args: argparse.Namespace) -> int:
    _memoria_require_storage_watchdog_ok()
    print("## MEMORIA MEMORY PROMOTION V0.1")
    print("------------------------------------------------------------")
    print("Explicit promotion only. No automatic memory write.")
    print("Token value is never printed.")
    print("Private chat logs are not scanned.")
    print()

    result = promote(args.candidate_id, keep_candidate_state=args.keep_candidate_state)

    print(f"OK   Candidate: {result['candidate']['id']}")
    print(f"OK   Candidate State: {result['candidate']['state']}")
    print(f"OK   Promoted To: {result['memory']['id']}")
    print(f"OK   Durable Memory: {result['memory_path']}")
    print("OK   Result: approved candidate promoted to durable memory")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Promote MEMORIA memory candidates")
    sub = parser.add_subparsers(dest="command", required=True)

    promote_cmd = sub.add_parser("promote")
    promote_cmd.add_argument("candidate_id")
    promote_cmd.add_argument(
        "--keep-candidate-state",
        action="store_true",
        help="keep candidate in user-approved state instead of archiving it after promotion",
    )
    promote_cmd.set_defaults(func=command_promote)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        return int(args.func(args))
    except FileNotFoundError as exc:
        print(f"FAIL Memory Promotion: not found {exc}")
        return 2
    except ValueError as exc:
        print(f"FAIL Memory Promotion: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
