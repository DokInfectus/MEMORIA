#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
from memoria_big_archive_group_runner import (
    load_bound_batch,
    validate_reducer_manifest,
)
from memoria_big_archive_reducer import sha256_file


SCHEMA_VERSION = "big-archive-render-v0.1"

STRING_LIST_FIELDS = (
    "themes",
    "important_memories",
    "projects_and_decisions",
    "uncertainties",
    "evidence",
)


def require_string_list(
    value: Any,
    *,
    location: str,
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{location} is not a list")

    result: list[str] = []

    for item in value:
        if not isinstance(item, str):
            raise ValueError(
                f"{location} contains a non-string value"
            )

        clean = item.strip()

        if clean:
            result.append(clean)

    return result


def normalize_entities(
    value: Any,
    *,
    allowed_blocks: set[int],
    location: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{location} is not a list")

    entities: list[dict[str, Any]] = []

    for position, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(
                f"{location}[{position}] is not an object"
            )

        name = str(item.get("name") or "").strip()
        description = str(
            item.get("description") or ""
        ).strip()
        raw_blocks = item.get("source_blocks")

        if not name:
            raise ValueError(
                f"{location}[{position}] has no name"
            )

        if not description:
            raise ValueError(
                f"{location}[{position}] has no description"
            )

        if not isinstance(raw_blocks, list) or not raw_blocks:
            raise ValueError(
                f"{location}[{position}] has invalid source_blocks"
            )

        source_blocks: list[int] = []

        for raw_block in raw_blocks:
            if isinstance(raw_block, bool):
                raise ValueError(
                    f"{location}[{position}] has invalid block reference"
                )

            block_number = int(raw_block)

            if block_number not in allowed_blocks:
                raise ValueError(
                    f"{location}[{position}] references foreign block "
                    f"{block_number}"
                )

            if block_number not in source_blocks:
                source_blocks.append(block_number)

        entities.append(
            {
                "name": name,
                "description": description,
                "source_blocks": sorted(source_blocks),
            }
        )

    return entities


def normalize_section(
    stored_group: Any,
    *,
    expected_number: int,
) -> dict[str, Any]:
    if not isinstance(stored_group, dict):
        raise ValueError(
            f"group {expected_number} is not an object"
        )

    metadata = stored_group.get("group")
    result = stored_group.get("result")

    if not isinstance(metadata, dict):
        raise ValueError(
            f"group {expected_number} metadata is invalid"
        )

    if not isinstance(result, dict):
        raise ValueError(
            f"group {expected_number} result is invalid"
        )

    group_number = int(metadata.get("group_number") or 0)

    if group_number != expected_number:
        raise ValueError(
            "renderer groups are not contiguous: "
            f"expected={expected_number}, stored={group_number}"
        )

    raw_blocks = metadata.get("source_blocks")

    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise ValueError(
            f"group {expected_number} source_blocks is invalid"
        )

    source_blocks = [int(number) for number in raw_blocks]

    title = str(result.get("title") or "").strip()
    summary = str(result.get("summary") or "").strip()

    if not title:
        raise ValueError(
            f"group {expected_number} title is empty"
        )

    if not summary:
        raise ValueError(
            f"group {expected_number} summary is empty"
        )

    section: dict[str, Any] = {
        "section_number": expected_number,
        "source_group": expected_number,
        "source_blocks": source_blocks,
        "title": title,
        "summary": summary,
    }

    for field in STRING_LIST_FIELDS:
        section[field] = require_string_list(
            result.get(field),
            location=f"group {expected_number}.{field}",
        )

    section["people_and_entities"] = normalize_entities(
        result.get("people_and_entities"),
        allowed_blocks=set(source_blocks),
        location=(
            f"group {expected_number}.people_and_entities"
        ),
    )

    rejections = result.get("entity_rejections", [])

    if not isinstance(rejections, list):
        raise ValueError(
            f"group {expected_number}.entity_rejections "
            "is not a list"
        )

    section["entity_rejections"] = rejections
    return section


def format_number_ranges(numbers: list[int]) -> str:
    if not numbers:
        return "-"

    values = sorted(set(numbers))
    ranges: list[str] = []
    start = previous = values[0]

    for value in values[1:]:
        if value == previous + 1:
            previous = value
            continue

        ranges.append(
            str(start)
            if start == previous
            else f"{start}–{previous}"
        )
        start = previous = value

    ranges.append(
        str(start)
        if start == previous
        else f"{start}–{previous}"
    )

    return ", ".join(ranges)


def append_string_section(
    lines: list[str],
    heading: str,
    items: list[str],
) -> None:
    if not items:
        return

    lines.extend(["", f"### {heading}"])

    for item in items:
        lines.append(f"- {item}")


def build_readable_text(
    *,
    source_name: str,
    sections: list[dict[str, Any]],
) -> str:
    lines = [
        "# MEMORIA Gedächtnisarchiv",
        "",
        f"Quelle: {source_name}",
        f"Abschnitte: {len(sections)}",
        (
            "Erzeugung: deterministisch aus geprüften "
            "Reducer-Gruppen; kein weiterer LLM-Aufruf."
        ),
    ]

    for section in sections:
        number = int(section["section_number"])

        lines.extend(
            [
                "",
                "---",
                "",
                (
                    f"## Abschnitt {number:02d}/{len(sections):02d} "
                    f"– {section['title']}"
                ),
                "",
                (
                    "Quellblöcke: "
                    + format_number_ranges(
                        section["source_blocks"]
                    )
                ),
                "",
                section["summary"],
            ]
        )

        append_string_section(
            lines,
            "Themen",
            section["themes"],
        )
        append_string_section(
            lines,
            "Wichtige Erinnerungen",
            section["important_memories"],
        )

        entities = section["people_and_entities"]

        if entities:
            lines.extend(["", "### Personen und Entitäten"])

            for entity in entities:
                blocks = format_number_ranges(
                    entity["source_blocks"]
                )
                lines.append(
                    f"- {entity['name']}: "
                    f"{entity['description']} "
                    f"[Quellblöcke: {blocks}]"
                )

        append_string_section(
            lines,
            "Projekte und Entscheidungen",
            section["projects_and_decisions"],
        )
        append_string_section(
            lines,
            "Unsicherheiten",
            section["uncertainties"],
        )
        append_string_section(
            lines,
            "Quellhinweise",
            section["evidence"],
        )

    return "\n".join(lines).rstrip() + "\n"


def render_archive(
    *,
    reducer_manifest_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    reducer_manifest_path = (
        reducer_manifest_path.expanduser().resolve()
    )
    output_path = output_path.expanduser().resolve()

    if not reducer_manifest_path.is_file():
        raise ValueError("reducer manifest does not exist")

    if output_path.exists():
        raise ValueError(
            "renderer output already exists; refusing to overwrite"
        )

    reducer_hash_before = sha256_file(
        reducer_manifest_path
    )
    reducer = load_json(reducer_manifest_path)

    validate_reducer_manifest(reducer)

    if reducer.get("status") != "groups-complete":
        raise ValueError(
            "reducer status must be groups-complete"
        )

    if reducer.get("final_result") is not None:
        raise ValueError(
            "reducer unexpectedly contains final_result"
        )

    batch_path, _batch = load_bound_batch(reducer)
    batch_hash_before = sha256_file(batch_path)

    source = reducer.get("source")

    if not isinstance(source, dict):
        raise ValueError("reducer source binding is invalid")

    source_path = Path(
        str(source.get("file") or "")
    ).expanduser().resolve()

    if not source_path.is_file():
        raise ValueError("bound source file does not exist")

    source_hash_before = sha256_file(source_path)
    groups = reducer.get("groups")

    if not isinstance(groups, list):
        raise ValueError("reducer groups field is invalid")

    total_groups = int(reducer.get("total_groups") or 0)

    if len(groups) != total_groups:
        raise ValueError(
            "stored reducer groups are incomplete"
        )

    sections = [
        normalize_section(
            stored_group,
            expected_number=position,
        )
        for position, stored_group in enumerate(
            groups,
            start=1,
        )
    ]

    source_name = str(
        source.get("name") or source_path.name
    )

    readable_text = build_readable_text(
        source_name=source_name,
        sections=sections,
    )

    rendered: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mode": "deterministic-no-llm-no-memory-write",
        "created_at": utc_now(),
        "bindings": {
            "reducer_manifest": {
                "file": str(reducer_manifest_path),
                "sha256": reducer_hash_before,
            },
            "batch_manifest": {
                "file": str(batch_path),
                "sha256": batch_hash_before,
            },
        },
        "source": dict(source),
        "archive": {
            "title": (
                "MEMORIA Gedächtnisarchiv – "
                + Path(source_name).stem
            ),
            "section_count": len(sections),
            "sections": sections,
            "readable_text": readable_text,
            "readable_text_chars": len(readable_text),
        },
        "policy": {
            "explicit_reducer_manifest_only": True,
            "private_directory_scan": False,
            "llm_called": False,
            "source_modified": False,
            "batch_manifest_modified": False,
            "reducer_manifest_modified": False,
            "candidate_written": False,
            "durable_memory_written": False,
            "automatic_promotion": False,
            "internal_archive_output_written": True,
        },
    }

    if sha256_file(reducer_manifest_path) != (
        reducer_hash_before
    ):
        raise RuntimeError(
            "reducer manifest changed during rendering"
        )

    if sha256_file(batch_path) != batch_hash_before:
        raise RuntimeError(
            "batch manifest changed during rendering"
        )

    if sha256_file(source_path) != source_hash_before:
        raise RuntimeError(
            "source file changed during rendering"
        )

    write_json_atomic(output_path, rendered)
    return rendered


def print_human(
    rendered: dict[str, Any],
    output_path: Path,
) -> None:
    archive = rendered["archive"]

    print("## MEMORIA BIG ARCHIVE RENDERER V0.1")
    print("Mode: DETERMINISTIC / NO LLM / NO MEMORY WRITE")
    print(f"Output: {output_path.expanduser().resolve()}")
    print(f"Sections: {archive['section_count']}")
    print(
        "Readable text chars: "
        f"{archive['readable_text_chars']}"
    )

    print("\nPolicy:")
    print("- LLM called: False")
    print("- Source modified: False")
    print("- Batch manifest modified: False")
    print("- Reducer manifest modified: False")
    print("- Candidate written: False")
    print("- Durable memory written: False")
    print("- Automatic promotion: False")
    print("- Internal archive output written: True")
    print("OK deterministic archive renderer checkpoint saved.")


def command_render(args: argparse.Namespace) -> int:
    try:
        rendered = render_archive(
            reducer_manifest_path=Path(args.manifest),
            output_path=Path(args.output),
        )
    except Exception as exc:
        print(f"ABORT: {exc}")
        return 23

    print_human(rendered, Path(args.output))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render completed Big Archive reducer groups into "
            "one deterministic internal archive file."
        )
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    render = sub.add_parser("render")
    render.add_argument("--manifest", required=True)
    render.add_argument("--output", required=True)
    render.set_defaults(func=command_render)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
