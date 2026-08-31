#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from memoria_memory_file_import import (
    chunk_text,
    load_settings,
    read_import_file,
    scan_sensitive,
    sha256_file,
)


SCHEMA_VERSION = "big-archive-section-manifest-v0.1"


@dataclass(frozen=True)
class Section:
    index: int
    source_chunk_start: int
    source_chunk_end: int
    chunk_count: int
    char_count: int
    title: str
    preview: str


def compact_text(text: str) -> str:
    return " ".join(str(text or "").split())


def first_meaningful_line(text: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^[-*+>]+\s*", "", line)
        line = compact_text(line)

        if line:
            return line

    return ""


def is_structural_heading(text: str) -> bool:
    first = next(
        (line.strip() for line in text.splitlines() if line.strip()),
        "",
    )

    if re.match(r"^#{1,6}\s+\S", first):
        return True

    return bool(
        re.match(
            r"^(sektion|section|kapitel|chapter|teil|part)\s+[\w\d]",
            first,
            flags=re.IGNORECASE,
        )
    )


def make_section(
    section_index: int,
    items: list[tuple[int, str]],
) -> Section:
    start = items[0][0]
    end = items[-1][0]
    texts = [text for _, text in items]

    title = first_meaningful_line(texts[0])
    if not title:
        title = f"Sektion {section_index:03d}"

    title = title[:96]
    preview = compact_text("\n\n".join(texts))[:180]

    return Section(
        index=section_index,
        source_chunk_start=start,
        source_chunk_end=end,
        chunk_count=len(items),
        char_count=sum(len(text) for text in texts),
        title=title,
        preview=preview,
    )


def build_sections(
    chunks: list[str],
    *,
    max_chunks: int,
    max_chars: int,
    min_chunks_before_heading_split: int,
) -> list[Section]:
    sections: list[Section] = []
    current: list[tuple[int, str]] = []
    current_chars = 0

    def flush() -> None:
        nonlocal current, current_chars

        if not current:
            return

        sections.append(make_section(len(sections) + 1, current))
        current = []
        current_chars = 0

    for chunk_index, chunk in enumerate(chunks, start=1):
        separator_chars = 2 if current else 0
        next_chars = current_chars + separator_chars + len(chunk)

        heading_boundary = (
            bool(current)
            and len(current) >= min_chunks_before_heading_split
            and is_structural_heading(chunk)
        )

        hard_boundary = bool(current) and (
            len(current) >= max_chunks
            or next_chars > max_chars
        )

        if heading_boundary or hard_boundary:
            flush()

        current.append((chunk_index, chunk))
        current_chars += (2 if len(current) > 1 else 0) + len(chunk)

    flush()
    return sections


def analyze_archive(
    path: Path,
    *,
    max_chunk_chars: int,
    section_max_chunks: int,
    section_max_chars: int,
    section_min_chunks: int,
) -> dict[str, Any]:
    settings = load_settings()
    allowed = {
        str(item).lower()
        for item in settings.get("allowed_extensions", [])
    }

    path = path.expanduser().resolve()

    if not path.exists():
        raise ValueError(f"file not found: {path}")

    if not path.is_file():
        raise ValueError(f"not a regular file: {path}")

    if path.suffix.lower() not in allowed:
        raise ValueError(f"extension not allowed: {path.suffix}")

    text = read_import_file(path)
    chunks = chunk_text(text, max_chars=max_chunk_chars)

    sections = build_sections(
        chunks,
        max_chunks=section_max_chunks,
        max_chars=section_max_chars,
        min_chunks_before_heading_split=section_min_chunks,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "read-only",
        "source": {
            "file": str(path),
            "name": path.name,
            "size_bytes": path.stat().st_size,
            "size_chars": len(text),
            "sha256": sha256_file(path),
        },
        "analysis": {
            "technical_chunks": len(chunks),
            "detected_sections": len(sections),
            "max_chunk_chars": max_chunk_chars,
            "section_max_chunks": section_max_chunks,
            "section_max_chars": section_max_chars,
            "section_min_chunks": section_min_chunks,
        },
        "warnings": scan_sensitive(text),
        "policy": {
            "explicit_file_only": True,
            "private_directory_scan": False,
            "source_modified": False,
            "candidate_written": False,
            "durable_memory_written": False,
        },
        "sections": [asdict(section) for section in sections],
    }


def print_human(manifest: dict[str, Any], summary_only: bool) -> None:
    source = manifest["source"]
    analysis = manifest["analysis"]
    policy = manifest["policy"]

    print("## MEMORIA BIG ARCHIVE SECTION ANALYZER V0.1")
    print("Mode: READ-ONLY")
    print(f"File: {source['file']}")
    print(f"Size bytes: {source['size_bytes']}")
    print(f"Size chars: {source['size_chars']}")
    print(f"Source SHA256: {source['sha256']}")
    print(f"Technical chunks: {analysis['technical_chunks']}")
    print(f"Detected sections: {analysis['detected_sections']}")
    print()

    warnings = manifest.get("warnings", [])
    if warnings:
        print("Warnings detected; no matched secret values are displayed:")
        for warning in warnings:
            print(f"- {warning}")
        print()

    if not summary_only:
        total = len(manifest["sections"])

        for section in manifest["sections"]:
            print(f"---- section {section['index']:03d}/{total:03d} ----")
            print(
                "Chunks: "
                f"{section['source_chunk_start']}-"
                f"{section['source_chunk_end']} "
                f"| count={section['chunk_count']} "
                f"| chars={section['char_count']}"
            )
            print(f"Title: {section['title']}")
            print(f"Preview: {section['preview']}")
            print()

    print("Policy:")
    print(f"- Source modified: {policy['source_modified']}")
    print(f"- Candidate written: {policy['candidate_written']}")
    print(f"- Durable memory written: {policy['durable_memory_written']}")
    print("- No private directory scan.")
    print("OK read-only section analysis completed.")


def command_analyze(args: argparse.Namespace) -> int:
    values = (
        args.max_chunk_chars,
        args.section_max_chunks,
        args.section_max_chars,
        args.section_min_chunks,
    )

    if any(value <= 0 for value in values):
        print("ABORT: analyzer limits must be greater than zero.")
        return 23

    if args.section_min_chunks > args.section_max_chunks:
        print("ABORT: section-min-chunks exceeds section-max-chunks.")
        return 23

    try:
        manifest = analyze_archive(
            Path(args.file),
            max_chunk_chars=args.max_chunk_chars,
            section_max_chunks=args.section_max_chunks,
            section_max_chars=args.section_max_chars,
            section_min_chunks=args.section_min_chunks,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ABORT: {exc}")
        return 23

    if args.json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print_human(manifest, summary_only=args.summary_only)

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MEMORIA read-only big archive section analyzer"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze")
    analyze.add_argument("--file", required=True)
    analyze.add_argument("--max-chunk-chars", type=int, default=1800)
    analyze.add_argument("--section-max-chunks", type=int, default=40)
    analyze.add_argument("--section-max-chars", type=int, default=60000)
    analyze.add_argument("--section-min-chunks", type=int, default=5)
    analyze.add_argument("--summary-only", action="store_true")
    analyze.add_argument("--json", action="store_true")
    analyze.set_defaults(func=command_analyze)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
