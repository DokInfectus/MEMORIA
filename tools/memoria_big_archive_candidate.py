#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / "tools"

for entry in (PROJECT_ROOT, TOOLS_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import memoria_memory_candidate_store as candidate_store

from memoria_big_archive_batch_runner import load_json
from memoria_big_archive_reducer import sha256_file


ARCHIVE_SCHEMA_VERSION = "big-archive-render-v0.1"
LINK_SCHEMA_VERSION = "big-archive-candidate-link-v0.1"
BATCH_SCHEMA_VERSION = "big-archive-batch-run-v0.1"
REDUCER_SCHEMA_VERSION = "big-archive-reducer-run-v0.1"

EXPECTED_MODE = "deterministic-no-llm-no-memory-write"

FORBIDDEN_TRUE_POLICY_KEYS = (
    "llm_called",
    "source_modified",
    "batch_manifest_modified",
    "reducer_manifest_modified",
    "candidate_written",
    "durable_memory_written",
    "automatic_promotion",
)


def require_bound_file(
    value: Any,
    *,
    location: str,
) -> Path:
    if not isinstance(value, dict):
        raise ValueError(f"{location} binding is invalid")

    path = Path(
        str(value.get("file") or "")
    ).expanduser().resolve()

    expected_hash = str(value.get("sha256") or "")

    if not path.is_file():
        raise ValueError(
            f"{location} bound file does not exist"
        )

    if not expected_hash:
        raise ValueError(
            f"{location} binding has no SHA-256"
        )

    if sha256_file(path) != expected_hash:
        raise ValueError(
            f"{location} bound file hash differs"
        )

    return path



def load_bound_source_metrics(
    *,
    source: dict[str, Any],
    source_path: Path,
    batch_path: Path,
    reducer_path: Path,
) -> dict[str, int]:
    """Validate and derive source metrics from bound pipeline files.

    No pipeline stage is executed here. The already SHA-bound source,
    batch manifest and reducer manifest are read only.
    """

    def require_integer(
        value: Any,
        *,
        location: str,
        minimum: int = 0,
    ) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{location} is not an integer")

        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{location} is not an integer"
            ) from exc

        if result < minimum:
            raise ValueError(
                f"{location} must be >= {minimum}"
            )

        return result

    source_size_bytes = source_path.stat().st_size
    declared_size = source.get("size_bytes")

    if declared_size not in (None, ""):
        if require_integer(
            declared_size,
            location="source size_bytes",
        ) != source_size_bytes:
            raise ValueError(
                "source size differs from renderer metadata"
            )

    try:
        source_text = source_path.read_text(
            encoding="utf-8"
        )
    except UnicodeDecodeError as exc:
        raise ValueError(
            "source file is not valid UTF-8"
        ) from exc

    source_char_count = len(source_text)
    declared_chars = source.get("char_count")

    # Older renderer output incorrectly stored zero. A positive declared
    # value is still treated as an integrity assertion.
    if declared_chars not in (None, "", 0, "0"):
        if require_integer(
            declared_chars,
            location="source char_count",
        ) != source_char_count:
            raise ValueError(
                "source character count differs "
                "from renderer metadata"
            )

    batch = load_json(batch_path)

    if batch.get("schema_version") != BATCH_SCHEMA_VERSION:
        raise ValueError(
            "unsupported bound Big Archive batch schema"
        )

    batch_source = batch.get("source")

    if not isinstance(batch_source, dict):
        raise ValueError("batch source binding is invalid")

    batch_source_path = Path(
        str(batch_source.get("file") or "")
    ).expanduser().resolve()

    if batch_source_path != source_path:
        raise ValueError(
            "batch source path differs from renderer source"
        )

    if str(batch_source.get("sha256") or "") != str(
        source.get("sha256") or ""
    ):
        raise ValueError(
            "batch source SHA-256 differs "
            "from renderer source"
        )

    blocks = batch.get("blocks")

    if not isinstance(blocks, list) or not blocks:
        raise ValueError("batch blocks are invalid")

    source_section_count = len(blocks)

    if require_integer(
        batch.get("total_blocks"),
        location="batch total_blocks",
        minimum=1,
    ) != source_section_count:
        raise ValueError(
            "batch total_blocks differs from block list"
        )

    if require_integer(
        batch.get("completed_blocks"),
        location="batch completed_blocks",
        minimum=1,
    ) != source_section_count:
        raise ValueError(
            "batch is not completely processed"
        )

    expected_chunk_start = 1
    technical_chunks: int | None = None

    for expected_number, entry in enumerate(
        blocks,
        start=1,
    ):
        if not isinstance(entry, dict):
            raise ValueError("batch block entry is invalid")

        block = entry.get("block")

        if not isinstance(block, dict):
            raise ValueError(
                "batch block metadata is invalid"
            )

        block_number = require_integer(
            block.get("block_number"),
            location="batch block_number",
            minimum=1,
        )
        block_count = require_integer(
            block.get("block_count"),
            location="batch block_count",
            minimum=1,
        )
        chunk_start = require_integer(
            block.get("source_chunk_start"),
            location="batch source_chunk_start",
            minimum=1,
        )
        chunk_end = require_integer(
            block.get("source_chunk_end"),
            location="batch source_chunk_end",
            minimum=1,
        )
        chunk_count = require_integer(
            block.get("chunk_count"),
            location="batch chunk_count",
            minimum=1,
        )
        declared_technical_chunks = require_integer(
            block.get("technical_chunk_count"),
            location="batch technical_chunk_count",
            minimum=1,
        )

        if block_number != expected_number:
            raise ValueError(
                "batch block numbers are not contiguous"
            )

        if block_count != source_section_count:
            raise ValueError(
                "batch block_count differs "
                "from total block count"
            )

        if chunk_start != expected_chunk_start:
            raise ValueError(
                "batch source chunk ranges are not contiguous"
            )

        if chunk_end < chunk_start:
            raise ValueError(
                "batch source chunk range is reversed"
            )

        if chunk_count != chunk_end - chunk_start + 1:
            raise ValueError(
                "batch chunk_count differs from chunk range"
            )

        if technical_chunks is None:
            technical_chunks = declared_technical_chunks
        elif technical_chunks != declared_technical_chunks:
            raise ValueError(
                "technical_chunk_count differs between blocks"
            )

        expected_chunk_start = chunk_end + 1

    if technical_chunks is None:
        raise ValueError(
            "batch contains no technical chunk count"
        )

    if expected_chunk_start - 1 != technical_chunks:
        raise ValueError(
            "final batch chunk does not match "
            "technical_chunk_count"
        )

    reducer = load_json(reducer_path)

    if reducer.get("schema_version") != (
        REDUCER_SCHEMA_VERSION
    ):
        raise ValueError(
            "unsupported bound Big Archive reducer schema"
        )

    reducer_batch_path = require_bound_file(
        reducer.get("batch_manifest"),
        location="reducer batch manifest",
    )

    if reducer_batch_path != batch_path:
        raise ValueError(
            "reducer references a different batch manifest"
        )

    reducer_source = reducer.get("source")

    if not isinstance(reducer_source, dict):
        raise ValueError("reducer source binding is invalid")

    reducer_source_path = Path(
        str(reducer_source.get("file") or "")
    ).expanduser().resolve()

    if reducer_source_path != source_path:
        raise ValueError(
            "reducer source path differs "
            "from renderer source"
        )

    if str(reducer_source.get("sha256") or "") != str(
        source.get("sha256") or ""
    ):
        raise ValueError(
            "reducer source SHA-256 differs "
            "from renderer source"
        )

    if require_integer(
        reducer.get("total_source_blocks"),
        location="reducer total_source_blocks",
        minimum=1,
    ) != source_section_count:
        raise ValueError(
            "reducer source block count differs from batch"
        )

    return {
        "size_bytes": source_size_bytes,
        "char_count": source_char_count,
        "technical_chunks": technical_chunks,
        "source_section_count": source_section_count,
    }



def load_validated_archive(
    archive_path: Path,
) -> dict[str, Any]:
    archive_path = archive_path.expanduser().resolve()

    if not archive_path.is_file():
        raise ValueError("archive file does not exist")

    document = load_json(archive_path)

    if document.get("schema_version") != (
        ARCHIVE_SCHEMA_VERSION
    ):
        raise ValueError(
            "unsupported Big Archive renderer schema"
        )

    if document.get("mode") != EXPECTED_MODE:
        raise ValueError(
            "archive was not produced by deterministic renderer"
        )

    policy = document.get("policy")

    if not isinstance(policy, dict):
        raise ValueError("archive policy is invalid")

    for key in FORBIDDEN_TRUE_POLICY_KEYS:
        if policy.get(key) is not False:
            raise ValueError(
                f"archive policy requires {key}=False"
            )

    if policy.get(
        "internal_archive_output_written"
    ) is not True:
        raise ValueError(
            "archive output checkpoint is not confirmed"
        )

    bindings = document.get("bindings")

    if not isinstance(bindings, dict):
        raise ValueError("archive bindings are invalid")

    reducer_path = require_bound_file(
        bindings.get("reducer_manifest"),
        location="reducer manifest",
    )
    batch_path = require_bound_file(
        bindings.get("batch_manifest"),
        location="batch manifest",
    )

    source = document.get("source")
    source_path = require_bound_file(
        source,
        location="source",
    )

    archive = document.get("archive")

    if not isinstance(archive, dict):
        raise ValueError("archive object is invalid")

    title = str(archive.get("title") or "").strip()
    readable_text = str(
        archive.get("readable_text") or ""
    ).strip()
    sections = archive.get("sections")
    section_count = archive.get("section_count")
    declared_chars = archive.get(
        "readable_text_chars"
    )

    if not title:
        raise ValueError("archive title is empty")

    if not readable_text:
        raise ValueError("archive readable text is empty")

    if not isinstance(sections, list) or not sections:
        raise ValueError("archive sections are invalid")

    if section_count != len(sections):
        raise ValueError(
            "archive section count differs from sections"
        )

    if declared_chars != len(
        str(archive.get("readable_text") or "")
    ):
        raise ValueError(
            "archive readable text character count differs"
        )

    expected_numbers = list(
        range(1, len(sections) + 1)
    )
    actual_numbers: list[int] = []

    for section in sections:
        if not isinstance(section, dict):
            raise ValueError(
                "archive contains an invalid section"
            )

        actual_numbers.append(
            int(section.get("section_number") or 0)
        )

    if actual_numbers != expected_numbers:
        raise ValueError(
            "archive section numbers are not contiguous"
        )

    source_metrics = load_bound_source_metrics(
        source=source,
        source_path=source_path,
        batch_path=batch_path,
        reducer_path=reducer_path,
    )

    return {
        "path": archive_path,
        "sha256": sha256_file(archive_path),
        "document": document,
        "archive": archive,
        "source": source,
        "source_path": source_path,
        "title": title,
        "readable_text": readable_text,
        "section_count": len(sections),
        "readable_text_chars": declared_chars,
        "source_size_bytes": source_metrics[
            "size_bytes"
        ],
        "source_char_count": source_metrics[
            "char_count"
        ],
        "technical_chunks": source_metrics[
            "technical_chunks"
        ],
        "source_section_count": source_metrics[
            "source_section_count"
        ],
    }


def candidate_link_metadata(
    validated: dict[str, Any],
) -> dict[str, Any]:
    source = validated["source"]

    return {
        "big_archive": {
            "schema_version": LINK_SCHEMA_VERSION,
            "renderer_schema_version": (
                ARCHIVE_SCHEMA_VERSION
            ),
            "archive_file": str(validated["path"]),
            "archive_sha256": validated["sha256"],
            "source_file": str(
                source.get("file") or ""
            ),
            "source_name": str(
                source.get("name") or ""
            ),
            "source_sha256": str(
                source.get("sha256") or ""
            ),
            "source_size_bytes": validated[
                "source_size_bytes"
            ],
            "source_char_count": validated[
                "source_char_count"
            ],
            "technical_chunks": validated[
                "technical_chunks"
            ],
            "source_section_count": validated[
                "source_section_count"
            ],
            "section_count": validated[
                "section_count"
            ],
            "readable_text_chars": validated[
                "readable_text_chars"
            ],
            "deterministic_renderer": True,
            "llm_finalizer_used": False,
        }
    }


def find_linked_candidates(
    archive_sha256: str,
) -> list[dict[str, Any]]:
    directory = candidate_store.CANDIDATE_DIR

    if not directory.exists():
        return []

    matches: list[dict[str, Any]] = []

    for path in sorted(directory.glob("CAND-*.json")):
        try:
            candidate = json.loads(
                path.read_text(encoding="utf-8")
            )
        except Exception:
            continue

        if not isinstance(candidate, dict):
            continue

        metadata = candidate.get("metadata")

        if not isinstance(metadata, dict):
            continue

        link = metadata.get("big_archive")

        if not isinstance(link, dict):
            continue

        if link.get("archive_sha256") == (
            archive_sha256
        ):
            matches.append(candidate)

    return matches


def prepare_candidate(
    archive_path: Path,
) -> dict[str, Any]:
    validated = load_validated_archive(
        archive_path
    )

    existing = find_linked_candidates(
        validated["sha256"]
    )

    if len(existing) > 1:
        ids = ", ".join(
            str(item.get("id"))
            for item in existing
        )
        raise ValueError(
            "multiple Candidates reference this archive: "
            + ids
        )

    if len(existing) == 1:
        return {
            "created": False,
            "candidate": existing[0],
            "validated": validated,
            "candidate_output": "",
        }

    before = set(
        candidate_store.CANDIDATE_DIR.glob(
            "CAND-*.json"
        )
    )

    metadata = candidate_link_metadata(validated)

    args = argparse.Namespace(
        title=validated["title"],
        text=validated["readable_text"],
        text_file=None,
        layer="user",
        source="big-archive-renderer",
        metadata_json=json.dumps(
            metadata,
            ensure_ascii=False,
            sort_keys=True,
        ),
        tags=(
            "big-archive,"
            "explicit-memory-file,"
            "sectioned-memory,"
            "deterministic-renderer"
        ),
    )

    output_buffer = io.StringIO()

    with redirect_stdout(output_buffer):
        result_code = candidate_store.command_create(
            args
        )

    candidate_output = output_buffer.getvalue()

    if result_code != 0:
        clean_output = candidate_output.strip()

        raise RuntimeError(
            "Candidate Store rejected archive"
            + (
                f":\n{clean_output}"
                if clean_output
                else ""
            )
        )

    match = re.search(
        r"OK\s+Candidate:\s+"
        r"(CAND-[0-9]{8}-[0-9]{6}-[a-f0-9]{8})",
        candidate_output,
    )

    if not match:
        after = set(
            candidate_store.CANDIDATE_DIR.glob(
                "CAND-*.json"
            )
        )
        created_paths = sorted(after - before)

        if len(created_paths) != 1:
            raise RuntimeError(
                "could not identify exactly one new Candidate"
            )

        candidate_id = created_paths[0].stem
    else:
        candidate_id = match.group(1)

    candidate = candidate_store.read_candidate(
        candidate_id
    )

    candidate_metadata = candidate.get("metadata")

    if not isinstance(candidate_metadata, dict):
        raise RuntimeError(
            "created Candidate has no metadata"
        )

    link = candidate_metadata.get("big_archive")

    if not isinstance(link, dict):
        raise RuntimeError(
            "created Candidate has no Big Archive link"
        )

    if link.get("archive_sha256") != (
        validated["sha256"]
    ):
        raise RuntimeError(
            "created Candidate archive binding differs"
        )

    linked = find_linked_candidates(
        validated["sha256"]
    )

    if len(linked) != 1:
        raise RuntimeError(
            "archive must reference exactly one Candidate"
        )

    return {
        "created": True,
        "candidate": candidate,
        "validated": validated,
        "candidate_output": candidate_output,
    }


def inspect_payload(
    validated: dict[str, Any],
) -> dict[str, Any]:
    linked = find_linked_candidates(
        validated["sha256"]
    )

    candidate_payload = None

    if len(linked) == 1:
        candidate = linked[0]
        candidate_payload = {
            "id": candidate.get("id"),
            "state": candidate.get("state"),
            "promoted_to": candidate.get("promoted_to"),
        }

    source = validated["source"]

    return {
        "schema_version": (
            "big-archive-candidate-inspect-v0.1"
        ),
        "mode": "read-only-no-memory-write",
        "archive": {
            "file": str(validated["path"]),
            "sha256": validated["sha256"],
            "title": validated["title"],
            "section_count": validated["section_count"],
            "readable_text_chars": (
                validated["readable_text_chars"]
            ),
        },
        "source": {
            "file": str(validated["source_path"]),
            "name": str(source.get("name") or ""),
            "sha256": str(source.get("sha256") or ""),
            "size_bytes": validated[
                "source_size_bytes"
            ],
            "char_count": validated[
                "source_char_count"
            ],
            "technical_chunks": validated[
                "technical_chunks"
            ],
            "source_section_count": validated[
                "source_section_count"
            ],
        },
        "linked_candidate_count": len(linked),
        "candidate": candidate_payload,
        "policy": {
            "archive_content_printed": False,
            "source_modified": False,
            "archive_modified": False,
            "candidate_written": False,
            "durable_memory_written": False,
        },
    }


def prepare_payload(
    result: dict[str, Any],
) -> dict[str, Any]:
    candidate = result["candidate"]
    validated = result["validated"]
    source = validated["source"]

    return {
        "schema_version": (
            "big-archive-candidate-prepare-v0.1"
        ),
        "mode": (
            "explicit-candidate-no-durable-memory-write"
        ),
        "archive": {
            "file": str(validated["path"]),
            "sha256": validated["sha256"],
            "title": validated["title"],
            "section_count": validated["section_count"],
            "readable_text_chars": (
                validated["readable_text_chars"]
            ),
        },
        "source": {
            "file": str(validated["source_path"]),
            "name": str(source.get("name") or ""),
            "sha256": str(source.get("sha256") or ""),
            "size_bytes": validated[
                "source_size_bytes"
            ],
            "char_count": validated[
                "source_char_count"
            ],
            "technical_chunks": validated[
                "technical_chunks"
            ],
            "source_section_count": validated[
                "source_section_count"
            ],
        },
        "created_this_invocation": bool(
            result["created"]
        ),
        "candidate": {
            "id": candidate.get("id"),
            "state": candidate.get("state"),
            "promoted_to": candidate.get("promoted_to"),
        },
        "policy": {
            "exactly_one_linked_candidate": True,
            "source_modified": False,
            "archive_modified": False,
            "durable_memory_written": False,
            "automatic_approval": False,
            "automatic_promotion": False,
        },
    }


def print_inspect(
    validated: dict[str, Any],
) -> None:
    linked = find_linked_candidates(
        validated["sha256"]
    )

    print("## MEMORIA BIG ARCHIVE CANDIDATE INSPECT V0.1")
    print("Mode: READ-ONLY / NO MEMORY WRITE")
    print(f"Archive: {validated['path']}")
    print(f"Archive SHA-256: {validated['sha256']}")
    print(f"Title: {validated['title']}")
    print(
        f"Sections: {validated['section_count']}"
    )
    print(
        "Readable text chars: "
        f"{validated['readable_text_chars']}"
    )
    print(
        f"Source: {validated['source_path']}"
    )
    print(f"Linked Candidates: {len(linked)}")

    if len(linked) == 1:
        candidate = linked[0]
        print(
            f"Candidate: {candidate.get('id')}"
        )
        print(
            f"Candidate state: "
            f"{candidate.get('state')}"
        )
        print(
            f"Promoted to: "
            f"{candidate.get('promoted_to')}"
        )

    print("\nPolicy:")
    print("- Archive content printed: False")
    print("- Source modified: False")
    print("- Archive modified: False")
    print("- Candidate written: False")
    print("- Durable memory written: False")


def print_prepare(result: dict[str, Any]) -> None:
    candidate = result["candidate"]

    print("## MEMORIA BIG ARCHIVE CANDIDATE PREPARE V0.1")
    print("Mode: EXPLICIT CANDIDATE / NO DURABLE MEMORY WRITE")
    print(
        f"Archive: {result['validated']['path']}"
    )
    print(
        f"Sections: "
        f"{result['validated']['section_count']}"
    )
    print(
        "Readable text chars: "
        f"{result['validated']['readable_text_chars']}"
    )
    print(
        f"Candidate created: {result['created']}"
    )
    print(f"Candidate: {candidate.get('id')}")
    print(
        f"Candidate state: {candidate.get('state')}"
    )
    print(
        f"Promoted to: {candidate.get('promoted_to')}"
    )

    print("\nPolicy:")
    print("- Exactly one linked Candidate: True")
    print("- Source modified: False")
    print("- Archive modified: False")
    print("- Durable memory written: False")
    print("- Automatic approval: False")
    print("- Automatic promotion: False")
    print(
        "OK Big Archive Candidate is ready "
        "for one explicit user decision."
    )


def command_inspect(args: argparse.Namespace) -> int:
    try:
        validated = load_validated_archive(
            Path(args.archive)
        )
    except Exception as exc:
        print(f"ABORT: {exc}")
        return 23

    if args.json:
        print(
            json.dumps(
                inspect_payload(validated),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    else:
        print_inspect(validated)

    return 0


def command_prepare(args: argparse.Namespace) -> int:
    try:
        result = prepare_candidate(
            Path(args.archive)
        )
    except Exception as exc:
        print(f"ABORT: {exc}")
        return 23

    if args.json:
        print(
            json.dumps(
                prepare_payload(result),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    else:
        print_prepare(result)

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare exactly one review Candidate from one "
            "validated deterministic Big Archive."
        )
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    inspect = sub.add_parser("inspect")
    inspect.add_argument("--archive", required=True)
    inspect.add_argument(
        "--json",
        action="store_true",
        help="print one machine-readable JSON object",
    )
    inspect.set_defaults(func=command_inspect)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--archive", required=True)
    prepare.add_argument(
        "--json",
        action="store_true",
        help="print one machine-readable JSON object",
    )
    prepare.set_defaults(func=command_prepare)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
