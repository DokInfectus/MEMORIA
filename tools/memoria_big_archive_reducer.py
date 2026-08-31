#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / "tools"

for entry in (PROJECT_ROOT, TOOLS_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from memoria_big_archive_batch_runner import (
    load_json,
    utc_now,
    write_json_atomic,
)


SCHEMA_VERSION = "big-archive-reducer-run-v0.1"
BATCH_SCHEMA_VERSION = "big-archive-batch-run-v0.1"
DEFAULT_GROUP_SIZE = 6


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def validate_no_write_policy(
    policy: Any,
    *,
    location: str,
) -> None:
    if not isinstance(policy, dict):
        raise ValueError(f"{location} policy is invalid")

    forbidden_true = (
        "source_modified",
        "candidate_written",
        "durable_memory_written",
        "automatic_promotion",
    )

    for key in forbidden_true:
        if policy.get(key) is True:
            raise ValueError(
                f"{location} policy reports forbidden write: {key}"
            )


def validate_batch_manifest(
    manifest: dict[str, Any],
) -> int:
    if manifest.get("schema_version") != BATCH_SCHEMA_VERSION:
        raise ValueError("unsupported batch manifest schema")

    if manifest.get("status") != "complete":
        raise ValueError("batch manifest is not complete")

    total_blocks = int(manifest.get("total_blocks") or 0)
    completed_blocks = int(
        manifest.get("completed_blocks") or 0
    )

    if total_blocks <= 0:
        raise ValueError("batch manifest has no source blocks")

    if completed_blocks != total_blocks:
        raise ValueError(
            "completed block count does not match total blocks"
        )

    if manifest.get("next_block") is not None:
        raise ValueError("complete batch still has a next block")

    blocks = manifest.get("blocks")

    if not isinstance(blocks, list):
        raise ValueError("batch blocks field is invalid")

    if len(blocks) != total_blocks:
        raise ValueError("batch block list is incomplete")

    source = manifest.get("source")

    if not isinstance(source, dict):
        raise ValueError("batch source field is invalid")

    source_sha256 = str(source.get("sha256") or "").strip()

    if not source_sha256:
        raise ValueError("batch source hash is missing")

    validate_no_write_policy(
        manifest.get("policy"),
        location="batch",
    )

    for position, entry in enumerate(blocks, start=1):
        if not isinstance(entry, dict):
            raise ValueError(
                f"batch block {position} is not an object"
            )

        block = entry.get("block")

        if not isinstance(block, dict):
            raise ValueError(
                f"batch block {position} metadata is invalid"
            )

        block_number = int(block.get("block_number") or 0)

        if block_number != position:
            raise ValueError(
                "batch block numbers are not contiguous: "
                f"position={position}, number={block_number}"
            )

        block_source = entry.get("source")

        if not isinstance(block_source, dict):
            raise ValueError(
                f"batch block {position} source is invalid"
            )

        if block_source.get("sha256") != source_sha256:
            raise ValueError(
                f"batch block {position} source hash differs"
            )

        validate_no_write_policy(
            entry.get("policy"),
            location=f"batch block {position}",
        )

        if not isinstance(entry.get("result"), dict):
            raise ValueError(
                f"batch block {position} result is invalid"
            )

    return total_blocks


def build_group_plan(
    total_blocks: int,
    group_size: int = DEFAULT_GROUP_SIZE,
) -> list[dict[str, Any]]:
    if total_blocks <= 0:
        raise ValueError("total blocks must be greater than zero")

    if group_size <= 0:
        raise ValueError("group size must be greater than zero")

    groups: list[dict[str, Any]] = []

    for start in range(1, total_blocks + 1, group_size):
        end = min(start + group_size - 1, total_blocks)

        groups.append(
            {
                "group_number": len(groups) + 1,
                "source_block_start": start,
                "source_block_end": end,
                "source_blocks": list(range(start, end + 1)),
                "status": "pending",
            }
        )

    return groups


def create_reducer_plan(
    *,
    batch_manifest_path: Path,
    reducer_manifest_path: Path,
    group_size: int = DEFAULT_GROUP_SIZE,
) -> dict[str, Any]:
    batch_manifest_path = (
        batch_manifest_path.expanduser().resolve()
    )
    reducer_manifest_path = (
        reducer_manifest_path.expanduser().resolve()
    )

    if not batch_manifest_path.is_file():
        raise ValueError("batch manifest does not exist")

    if reducer_manifest_path.exists():
        raise ValueError(
            "reducer manifest already exists; "
            "refusing to overwrite it"
        )

    if not reducer_manifest_path.parent.is_dir():
        raise ValueError(
            "reducer manifest parent directory does not exist"
        )

    batch_manifest = load_json(batch_manifest_path)
    total_blocks = validate_batch_manifest(batch_manifest)
    group_plan = build_group_plan(total_blocks, group_size)

    created_at = utc_now()

    reducer_manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mode": "local-checkpointed-no-memory-write",
        "status": "planned",
        "created_at": created_at,
        "updated_at": created_at,
        "batch_manifest": {
            "file": str(batch_manifest_path),
            "sha256": sha256_file(batch_manifest_path),
            "schema_version": batch_manifest.get(
                "schema_version"
            ),
        },
        "source": dict(batch_manifest["source"]),
        "runtime": dict(batch_manifest.get("runtime") or {}),
        "group_size": group_size,
        "total_source_blocks": total_blocks,
        "total_groups": len(group_plan),
        "completed_groups": 0,
        "next_group": 1,
        "group_plan": group_plan,
        "groups": [],
        "final_result": None,
        "last_error": None,
        "policy": {
            "explicit_batch_manifest_only": True,
            "local_backend_only": True,
            "private_directory_scan": False,
            "batch_manifest_modified": False,
            "source_modified": False,
            "candidate_written": False,
            "durable_memory_written": False,
            "automatic_promotion": False,
            "archive_result_written": False,
            "checkpoint_manifest_written": True,
        },
    }

    write_json_atomic(
        reducer_manifest_path,
        reducer_manifest,
    )

    return reducer_manifest


def print_plan(
    manifest: dict[str, Any],
    manifest_path: Path,
) -> None:
    print("## MEMORIA BIG ARCHIVE REDUCER PLAN V0.1")
    print("Mode: LOCAL / CHECKPOINTED / NO MEMORY WRITE")
    print(f"Manifest: {manifest_path.expanduser().resolve()}")
    print(f"Status: {manifest['status']}")
    print(
        "Source blocks: "
        f"{manifest['total_source_blocks']}"
    )
    print(f"Reducer groups: {manifest['total_groups']}")

    for group in manifest["group_plan"]:
        print(
            f"- Group {group['group_number']}: "
            f"blocks {group['source_block_start']}-"
            f"{group['source_block_end']}"
        )

    print("\nPolicy:")
    print("- Source modified: False")
    print("- Batch manifest modified: False")
    print("- Candidate written: False")
    print("- Durable memory written: False")
    print("- Automatic promotion: False")
    print("- Reducer checkpoint written: True")
    print("OK reducer plan checkpoint saved.")


def command_plan(args: argparse.Namespace) -> int:
    try:
        manifest = create_reducer_plan(
            batch_manifest_path=Path(args.batch_manifest),
            reducer_manifest_path=Path(args.manifest),
            group_size=args.group_size,
        )
    except Exception as exc:
        print(f"ABORT: {exc}")
        return 23

    print_plan(manifest, Path(args.manifest))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plan a checkpointed reduction of a completed "
            "MEMORIA Big Archive batch."
        )
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    plan = sub.add_parser("plan")
    plan.add_argument("--batch-manifest", required=True)
    plan.add_argument("--manifest", required=True)
    plan.add_argument(
        "--group-size",
        type=int,
        default=DEFAULT_GROUP_SIZE,
    )
    plan.set_defaults(func=command_plan)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
