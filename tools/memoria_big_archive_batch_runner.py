#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / "tools"

for entry in (PROJECT_ROOT, TOOLS_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from adapter.factory import build_adapter
from configure.manager import ConfigureManager
from memoria_big_archive_block_summarizer import (
    apply_output_budget,
    build_prompt,
    load_block,
    require_local_runtime,
    summarize_block,
)
from memoria_big_archive_section_analyzer import analyze_archive
from memoria_memory_file_import import sha256_file


SCHEMA_VERSION = "big-archive-batch-run-v0.1"
DEFAULT_CONTEXT_HEADROOM = 4096
DEFAULT_CHARS_PER_TOKEN = 3.0


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
    )


def write_json_atomic(
    path: Path,
    data: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_name(path.name + ".tmp")

    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(
            data,
            handle,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())

    os.replace(temporary, path)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(value, dict):
        raise ValueError("batch manifest must contain a JSON object")

    return value


def runtime_signature(
    runtime: dict[str, Any],
) -> dict[str, Any]:
    # Store no secrets or authentication values.
    return {
        "adapter": runtime.get("adapter"),
        "base_url": runtime.get("base_url"),
        "model": runtime.get("model"),
        "context_length": runtime.get("context_length"),
        "max_tokens": runtime.get("max_tokens"),
        "prompt_profile": runtime.get("prompt_profile"),
        "profile": runtime.get("profile"),
    }


def estimate_prompt_tokens(
    prompt: str,
    chars_per_token: float,
) -> int:
    if chars_per_token <= 0:
        raise ValueError("chars-per-token must be greater than zero")

    return max(
        1,
        math.ceil(len(prompt) / chars_per_token),
    )


def preflight_prompt(
    *,
    prompt: str,
    runtime: dict[str, Any],
    headroom_tokens: int,
    chars_per_token: float,
) -> dict[str, Any]:
    context_length = int(
        runtime.get("context_length") or 0
    )
    output_tokens = int(
        runtime.get("max_tokens") or 0
    )

    estimated_prompt_tokens = estimate_prompt_tokens(
        prompt,
        chars_per_token,
    )

    estimated_total = (
        estimated_prompt_tokens
        + output_tokens
        + headroom_tokens
    )

    if context_length > 0 and estimated_total > context_length:
        raise ValueError(
            "estimated context budget exceeded: "
            f"prompt={estimated_prompt_tokens}, "
            f"output={output_tokens}, "
            f"headroom={headroom_tokens}, "
            f"total={estimated_total}, "
            f"context={context_length}"
        )

    return {
        "method": "conservative-character-estimate",
        "prompt_chars": len(prompt),
        "chars_per_token": chars_per_token,
        "estimated_prompt_tokens": estimated_prompt_tokens,
        "requested_output_tokens": output_tokens,
        "reserved_headroom_tokens": headroom_tokens,
        "estimated_total_tokens": estimated_total,
        "context_length": context_length,
        "allowed": True,
    }


def analyzer_settings(
    *,
    max_chunk_chars: int,
    section_max_chunks: int,
    section_max_chars: int,
    section_min_chunks: int,
) -> dict[str, int]:
    return {
        "max_chunk_chars": max_chunk_chars,
        "section_max_chunks": section_max_chunks,
        "section_max_chars": section_max_chars,
        "section_min_chunks": section_min_chunks,
    }


def validate_completed_blocks(
    manifest: dict[str, Any],
) -> None:
    blocks = manifest.get("blocks")

    if not isinstance(blocks, list):
        raise ValueError("batch manifest blocks field is invalid")

    numbers = [
        int(item["block"]["block_number"])
        for item in blocks
    ]

    expected = list(range(1, len(numbers) + 1))

    if numbers != expected:
        raise ValueError(
            "completed blocks are not contiguous from block 1"
        )


def validate_resume(
    manifest: dict[str, Any],
    *,
    source_path: Path,
    source_sha256: str,
    settings: dict[str, int],
    runtime: dict[str, Any],
    total_blocks: int,
) -> None:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported batch manifest schema")

    source = manifest.get("source") or {}

    if source.get("file") != str(source_path):
        raise ValueError("resume source path does not match")

    if source.get("sha256") != source_sha256:
        raise ValueError(
            "resume source hash changed; source was modified"
        )

    if manifest.get("analyzer_settings") != settings:
        raise ValueError(
            "resume analyzer settings do not match"
        )

    if manifest.get("runtime") != runtime_signature(runtime):
        raise ValueError(
            "resume runtime/model/output settings do not match"
        )

    if int(manifest.get("total_blocks") or 0) != total_blocks:
        raise ValueError(
            "resume block count changed"
        )

    validate_completed_blocks(manifest)


def create_manifest(
    *,
    source_path: Path,
    source_sha256: str,
    source_size: int,
    source_chars: int,
    total_blocks: int,
    settings: dict[str, int],
    runtime: dict[str, Any],
    headroom_tokens: int,
    chars_per_token: float,
) -> dict[str, Any]:
    now = utc_now()

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "running",
        "created_at": now,
        "updated_at": now,
        "source": {
            "file": str(source_path),
            "name": source_path.name,
            "size_bytes": source_size,
            "char_count": source_chars,
            "sha256": source_sha256,
        },
        "analyzer_settings": settings,
        "runtime": runtime_signature(runtime),
        "preflight_policy": {
            "context_headroom_tokens": headroom_tokens,
            "chars_per_token": chars_per_token,
            "method": "conservative-character-estimate",
        },
        "total_blocks": total_blocks,
        "completed_blocks": 0,
        "next_block": 1,
        "blocks": [],
        "last_error": None,
        "policy": {
            "explicit_file_only": True,
            "local_backend_only": True,
            "private_directory_scan": False,
            "source_modified": False,
            "candidate_written": False,
            "durable_memory_written": False,
            "checkpoint_manifest_written": True,
            "automatic_promotion": False,
        },
    }


def run_batch(
    *,
    source_path: Path,
    manifest_path: Path,
    adapter: Any,
    runtime_label: dict[str, Any],
    max_output_tokens: int,
    max_chunk_chars: int = 1800,
    section_max_chunks: int = 40,
    section_max_chars: int = 60000,
    section_min_chunks: int = 5,
    limit_blocks: int = 1,
    resume: bool = False,
    headroom_tokens: int = DEFAULT_CONTEXT_HEADROOM,
    chars_per_token: float = DEFAULT_CHARS_PER_TOKEN,
) -> dict[str, Any]:
    if limit_blocks < 1:
        raise ValueError("limit-blocks must be at least 1")

    if headroom_tokens < 0:
        raise ValueError(
            "context headroom must not be negative"
        )

    source_path = source_path.expanduser().resolve()
    manifest_path = manifest_path.expanduser().resolve()

    runtime = apply_output_budget(
        runtime_label,
        max_output_tokens,
    )
    require_local_runtime(runtime)

    settings = analyzer_settings(
        max_chunk_chars=max_chunk_chars,
        section_max_chunks=section_max_chunks,
        section_max_chars=section_max_chars,
        section_min_chunks=section_min_chunks,
    )

    analysis = analyze_archive(
        source_path,
        max_chunk_chars=max_chunk_chars,
        section_max_chunks=section_max_chunks,
        section_max_chars=section_max_chars,
        section_min_chunks=section_min_chunks,
    )

    total_blocks = len(analysis["sections"])
    source_sha256 = sha256_file(source_path)
    source_size = source_path.stat().st_size
    source_chars = int(
        analysis["source"].get("char_count") or 0
    )

    if manifest_path.exists():
        if not resume:
            raise ValueError(
                "batch manifest already exists; "
                "use --resume or choose another manifest"
            )

        manifest = load_json(manifest_path)

        validate_resume(
            manifest,
            source_path=source_path,
            source_sha256=source_sha256,
            settings=settings,
            runtime=runtime,
            total_blocks=total_blocks,
        )
    else:
        if resume:
            raise ValueError(
                "cannot resume because batch manifest does not exist"
            )

        manifest = create_manifest(
            source_path=source_path,
            source_sha256=source_sha256,
            source_size=source_size,
            source_chars=source_chars,
            total_blocks=total_blocks,
            settings=settings,
            runtime=runtime,
            headroom_tokens=headroom_tokens,
            chars_per_token=chars_per_token,
        )
        write_json_atomic(manifest_path, manifest)

    completed = int(manifest.get("completed_blocks") or 0)
    processed_this_run = 0

    for block_number in range(
        completed + 1,
        total_blocks + 1,
    ):
        if processed_this_run >= limit_blocks:
            break

        try:
            block, block_text = load_block(
                source_path,
                block_number=block_number,
                max_chunk_chars=max_chunk_chars,
                section_max_chunks=section_max_chunks,
                section_max_chars=section_max_chars,
                section_min_chunks=section_min_chunks,
            )

            prompt = build_prompt(
                source_name=source_path.name,
                block=block,
                block_text=block_text,
            )

            preflight = preflight_prompt(
                prompt=prompt,
                runtime=runtime,
                headroom_tokens=headroom_tokens,
                chars_per_token=chars_per_token,
            )

            summary = summarize_block(
                source_path=source_path,
                block_number=block_number,
                adapter=adapter,
                runtime_label=runtime,
                max_chunk_chars=max_chunk_chars,
                section_max_chunks=section_max_chunks,
                section_max_chars=section_max_chars,
                section_min_chunks=section_min_chunks,
            )

            summary["batch_preflight"] = preflight
            manifest["blocks"].append(summary)

            completed = block_number
            processed_this_run += 1

            manifest["completed_blocks"] = completed
            manifest["next_block"] = (
                completed + 1
                if completed < total_blocks
                else None
            )
            manifest["status"] = "running"
            manifest["last_error"] = None
            manifest["updated_at"] = utc_now()

            # Green checkpoint after exactly one completed block.
            write_json_atomic(manifest_path, manifest)

        except Exception as exc:
            manifest["status"] = "stopped-on-error"
            manifest["next_block"] = block_number
            manifest["last_error"] = {
                "block_number": block_number,
                "message": str(exc),
                "timestamp": utc_now(),
            }
            manifest["updated_at"] = utc_now()
            write_json_atomic(manifest_path, manifest)
            raise

    if completed >= total_blocks:
        manifest["status"] = "complete"
        manifest["next_block"] = None
    else:
        manifest["status"] = "paused"

    manifest["completed_blocks"] = completed
    manifest["updated_at"] = utc_now()
    manifest["last_invocation"] = {
        "processed_blocks": processed_this_run,
        "limit_blocks": limit_blocks,
        "timestamp": utc_now(),
    }

    write_json_atomic(manifest_path, manifest)
    return manifest


def print_human(
    manifest: dict[str, Any],
    manifest_path: Path,
) -> None:
    print("## MEMORIA BIG ARCHIVE BATCH RUNNER V0.1")
    print("Mode: LOCAL / CHECKPOINTED / NO MEMORY WRITE")
    print(f"Source: {manifest['source']['file']}")
    print(f"Manifest: {manifest_path}")
    print(f"Status: {manifest['status']}")
    print(
        "Progress: "
        f"{manifest['completed_blocks']}/"
        f"{manifest['total_blocks']}"
    )
    print(f"Next block: {manifest.get('next_block')}")
    print(
        "Processed this invocation: "
        f"{manifest['last_invocation']['processed_blocks']}"
    )
    print()
    print("Policy:")
    print("- Source modified: False")
    print("- Candidate written: False")
    print("- Durable memory written: False")
    print("- Automatic promotion: False")
    print("- Checkpoint manifest written: True")

    if manifest["status"] == "complete":
        print("OK all archive blocks summarized.")
    else:
        print("OK batch checkpoint saved; resume required.")


def command_run(args: argparse.Namespace) -> int:
    try:
        config = ConfigureManager().load_runtime_config()
        adapter = build_adapter(
            apply_output_budget(
                config,
                args.max_output_tokens,
            )
        )

        manifest = run_batch(
            source_path=Path(args.file),
            manifest_path=Path(args.manifest),
            adapter=adapter,
            runtime_label=config,
            max_output_tokens=args.max_output_tokens,
            max_chunk_chars=args.max_chunk_chars,
            section_max_chunks=args.section_max_chunks,
            section_max_chars=args.section_max_chars,
            section_min_chunks=args.section_min_chunks,
            limit_blocks=args.limit_blocks,
            resume=args.resume,
            headroom_tokens=args.context_headroom,
            chars_per_token=args.chars_per_token,
        )
    except Exception as exc:
        print(f"ABORT: {exc}")
        return 23

    if args.json:
        print(
            json.dumps(
                manifest,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    else:
        print_human(
            manifest,
            Path(args.manifest).expanduser().resolve(),
        )

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Checkpointed local Big Archive block runner. "
            "No Candidate or durable-memory write."
        )
    )
    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    run = sub.add_parser("run")
    run.add_argument("--file", required=True)
    run.add_argument("--manifest", required=True)
    run.add_argument(
        "--max-output-tokens",
        type=int,
        default=20000,
    )
    run.add_argument(
        "--limit-blocks",
        type=int,
        default=1,
        help=(
            "Maximum new blocks processed in this invocation. "
            "Safe default: 1."
        ),
    )
    run.add_argument("--resume", action="store_true")
    run.add_argument("--max-chunk-chars", type=int, default=1800)
    run.add_argument("--section-max-chunks", type=int, default=40)
    run.add_argument("--section-max-chars", type=int, default=60000)
    run.add_argument("--section-min-chunks", type=int, default=5)
    run.add_argument(
        "--context-headroom",
        type=int,
        default=DEFAULT_CONTEXT_HEADROOM,
    )
    run.add_argument(
        "--chars-per-token",
        type=float,
        default=DEFAULT_CHARS_PER_TOKEN,
    )
    run.add_argument("--json", action="store_true")
    run.set_defaults(func=command_run)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
