#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(
    os.environ.get(
        "MEMORIA_MEMORY_IMPORT_SETTINGS",
        str(PROJECT_ROOT / "config" / "memory_import_settings.json"),
    )
)

DEFAULT_SETTINGS = {
    "schema_version": "memory-import-settings-v0.1",
    "enabled": True,
    "allowed_extensions": [".txt", ".json", ".md"],
    "default_max_chunk_chars": 1800,
    "default_max_chunks_per_run": 50,
    "create_candidates_only": True,
    "direct_durable_import_allowed": False,
    "requires_confirmation": "IMPORT_FILE_CANDIDATES",
    "policy": {
        "explicit_file_only": True,
        "no_private_directory_scan": True,
        "no_direct_durable_memory_by_default": True,
        "uses_memory_intake_filter": True,
        "candidates_require_review": True,
    },
}

SENSITIVE_PATTERNS = (
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "possible OpenAI-style API key"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE), "possible bearer token"),
    (re.compile(r"\b(api[_ -]?key|password|passwd|secret|token)\b\s*[:=]", re.IGNORECASE), "secret-like assignment"),
)


def load_settings() -> dict[str, Any]:
    data = dict(DEFAULT_SETTINGS)

    if CONFIG_PATH.exists():
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        data.update(loaded)
        policy = dict(DEFAULT_SETTINGS["policy"])
        policy.update(loaded.get("policy", {}))
        data["policy"] = policy

    return data


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def extract_strings_from_json(value: Any) -> list[str]:
    result: list[str] = []

    if isinstance(value, str):
        text = value.strip()
        if len(text) >= 10:
            result.append(text)

    elif isinstance(value, list):
        for item in value:
            result.extend(extract_strings_from_json(item))

    elif isinstance(value, dict):
        # Common chat export shapes: role/content/text/message/parts.
        preferred_keys = ["role", "author", "sender", "content", "text", "message", "parts"]

        preferred_text: list[str] = []
        for key in preferred_keys:
            if key in value:
                preferred_text.extend(extract_strings_from_json(value[key]))

        if preferred_text:
            result.append("\n".join(preferred_text))

        for key, item in value.items():
            if key not in preferred_keys:
                result.extend(extract_strings_from_json(item))

    return result


def read_json_file(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    strings = extract_strings_from_json(data)
    return "\n\n".join(strings)


def read_import_file(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix in (".txt", ".md"):
        return read_text_file(path)

    if suffix == ".json":
        return read_json_file(path)

    raise SystemExit(f"ABORT unsupported file extension: {suffix}")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scan_sensitive(text: str) -> list[str]:
    warnings: list[str] = []
    for pattern, label in SENSITIVE_PATTERNS:
        if pattern.search(text):
            warnings.append(label)
    return warnings


def chunk_text(text: str, max_chars: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""

            for i in range(0, len(paragraph), max_chars):
                piece = paragraph[i:i + max_chars].strip()
                if piece:
                    chunks.append(piece)
            continue

        if not current:
            current = paragraph
        elif len(current) + 2 + len(paragraph) <= max_chars:
            current += "\n\n" + paragraph
        else:
            chunks.append(current.strip())
            current = paragraph

    if current.strip():
        chunks.append(current.strip())

    return chunks


def run_intake(
    chunk: str,
    create_candidate: bool,
    metadata: dict[str, Any] | None = None,
    user_declared_memory: bool = False,
) -> tuple[int, str]:
    """Run Memory Intake using a temporary text file.

    Large imported chunks must not be passed as command-line arguments.
    Passing multi-MB text via argv can hit Linux ARG_MAX and fail with:
    OSError: [Errno 7] Argument list too long.
    """
    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            prefix="memoria-import-chunk-",
            suffix=".txt",
            delete=False,
        ) as temp:
            temp.write(chunk)
            temp_path = Path(temp.name)

        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "memoria_memory_intake.py"),
            "analyze",
            "--text-file",
            str(temp_path),
        ]

        if metadata:
            cmd.extend([
                "--metadata-json",
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            ])

        if user_declared_memory:
            cmd.append("--user-declared-memory")

        if create_candidate:
            cmd.append("--create-candidate")

        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        return result.returncode, result.stdout.strip()
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


def command_status(args: argparse.Namespace) -> int:
    settings = load_settings()
    print("## MEMORIA MEMORY FILE IMPORT SETTINGS V0.1")
    print(f"Config: {CONFIG_PATH}")
    print(f"Enabled: {settings.get('enabled')}")
    print(f"Allowed extensions: {', '.join(settings.get('allowed_extensions', []))}")
    print(f"Default max chunk chars: {settings.get('default_max_chunk_chars')}")
    print(f"Default max chunks per run: {settings.get('default_max_chunks_per_run')}")
    print(f"Create candidates only: {settings.get('create_candidates_only')}")
    print(f"Direct durable import allowed: {settings.get('direct_durable_import_allowed')}")
    print(f"Confirmation: {settings.get('requires_confirmation')}")
    print("Policy: explicit file only, no private directory scan, intake filter first.")
    return 0


def command_import(args: argparse.Namespace) -> int:
    settings = load_settings()

    if not settings.get("enabled", True):
        print("ABORT: memory file import is disabled in settings.")
        return 23

    path = Path(args.file).expanduser().resolve()

    if not path.exists():
        print(f"ABORT: file not found: {path}")
        return 23

    if not path.is_file():
        print(f"ABORT: not a regular file: {path}")
        return 23

    if path.suffix.lower() not in settings.get("allowed_extensions", []):
        print(f"ABORT: extension not allowed: {path.suffix}")
        return 23

    max_chars = args.max_chunk_chars or int(settings.get("default_max_chunk_chars", 1800))
    max_chunks = args.max_chunks or int(settings.get("default_max_chunks_per_run", 50))

    text = read_import_file(path)
    warnings = scan_sensitive(text)
    source_sha256 = sha256_file(path)
    imported_at = utc_now()

    print("## MEMORIA MEMORY FILE IMPORT V0.2")
    print("Explicit file import. No private directory scan. No direct durable memory.")
    print(f"File: {path}")
    print(f"Size chars: {len(text)}")
    print(f"Source SHA256: {source_sha256}")
    print(f"Mode: {'CREATE CANDIDATES' if args.apply else 'DRY RUN'}")
    print(f"Import mode: {args.import_mode}")
    print()

    if warnings:
        print("ABORT: sensitive-looking content detected. Clean/redact the file first.")
        for item in warnings:
            print(f"- {item}")
        return 23

    all_chunks = chunk_text(text, max_chars=max_chars)
    source_total_chunks = len(all_chunks)
    chunks = list(all_chunks)

    if len(chunks) > max_chunks:
        print(f"INFO: chunk count {len(chunks)} exceeds max {max_chunks}; truncating this run.")
        chunks = chunks[:max_chunks]

    print(f"Chunks this run: {len(chunks)}")
    print()

    if args.apply:
        if args.import_mode == "user-declared":
            answer = (args.confirm or "").strip().lower()
            if not answer and sys.stdin.isatty():
                answer = input("Diese Datei als Gedächtnisdatei übernehmen? [ja/nein]: ").strip().lower()

            if answer not in {"ja", "j", "yes", "y"}:
                print("ABORT: user-declared memory import not confirmed.")
                print("Confirm with --confirm ja or answer ja interactively.")
                return 23
        else:
            expected = str(settings.get("requires_confirmation", "IMPORT_FILE_CANDIDATES"))
            if args.confirm != expected:
                print("ABORT: confirmation mismatch.")
                print(f"To create candidates from this file, type exactly: {expected}")
                return 23

    created_or_processed = 0

    for index, chunk in enumerate(chunks, start=1):
        preview = " ".join(chunk.split())[:120]
        print(f"---- chunk {index}/{len(chunks)} ----")
        print(f"Preview: {preview}")

        metadata = {
            "schema_version": "memory-import-provenance-v0.2",
            "source_file": str(path),
            "source_name": path.name,
            "source_sha256": source_sha256,
            "source_total_chunks": source_total_chunks,
            "chunk_index": index,
            "chunk_count": len(chunks),
            "chunk_sha256": sha256_text(chunk),
            "import_mode": args.import_mode,
            "import_apply": bool(args.apply),
            "imported_at": imported_at,
            "tool": "memoria_memory_file_import.py",
        }

        print(f"Provenance: chunk {index}/{len(chunks)} source_sha256={source_sha256[:12]}...")

        code, output = run_intake(
            chunk,
            create_candidate=args.apply,
            metadata=metadata,
            user_declared_memory=args.import_mode == "user-declared",
        )
        print(output)

        if code != 0:
            print(f"ABORT: memory intake failed on chunk {index} with exit code {code}")
            return code

        created_or_processed += 1
        print()

    print(f"OK file import completed. Chunks processed: {created_or_processed}")
    if not args.apply:
        print("DRY RUN only. No candidates were created.")
    else:
        print("Candidates created according to selected import mode; user-declared mode bypasses relevance filtering but keeps safety and dedup.")
        print("Review with: python3 tools/memoria_memory_candidate_store.py list")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MEMORIA memory file import")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status")
    status.set_defaults(func=command_status)

    imp = sub.add_parser("import")
    imp.add_argument("--file", required=True)
    imp.add_argument("--apply", action="store_true")
    imp.add_argument("--confirm", default="")
    imp.add_argument("--max-chunk-chars", type=int, default=None)
    imp.add_argument("--max-chunks", type=int, default=None)
    imp.add_argument("--import-mode", default="filtered", choices=["filtered", "user-declared"])
    imp.set_defaults(func=command_import)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
