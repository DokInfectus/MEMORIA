#!/usr/bin/env python3
"""
MEMORIA Memory Store V0.1

Manual, user-approved memory storage.

Safety rules:
- no automatic memory creation
- no chat scraping
- no private directory scanning
- no installer backup behavior
- no secrets printed
"""

import argparse
import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from memoria_storage_paths import managed_path as _memoria_managed_path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEMORY_DIR = _memoria_managed_path(
    "memory",
    "MEMORIA_MEMORY_DIR",
    "knowledge/memory",
)
CANDIDATE_DIR = _memoria_managed_path(
    "memory_candidates",
    "MEMORIA_CANDIDATE_DIR",
    "knowledge/memory_candidates",
)
MEMORY_TRASH_DIR = MEMORY_DIR.parent / "memory_trash"
VERSION = "0.1.0-memory-store"
VALID_MEMORY_STATUSES = {"active", "disabled", "archived"}


@dataclass
class MemoryRecord:
    id: str
    title: str
    category: str
    content: str
    tags: List[str] = field(default_factory=list)
    status: str = "active"
    source_session: Optional[str] = None
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)
    version: str = VERSION

    def to_json_dict(self) -> dict:
        data = asdict(self)
        data["created"] = self.created.isoformat()
        data["updated"] = self.updated.isoformat()
        return data

    @classmethod
    def from_json_dict(cls, data: dict) -> "MemoryRecord":
        created = data.get("created")
        updated = data.get("updated")

        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        if isinstance(updated, str):
            updated = datetime.fromisoformat(updated)

        return cls(
            id=data["id"],
            title=data["title"],
            category=data.get("category", "memory"),
            content=data["content"],
            tags=data.get("tags", []),
            status=data.get("status", "active"),
            source_session=data.get("source_session"),
            created=created or datetime.now(),
            updated=updated or datetime.now(),
            version=data.get("version", VERSION),
        )


def status(label: str, message: str, ok=True) -> None:
    prefix = "OK" if ok is True else "INFO" if ok is None else "FAIL"
    print(f"{prefix}  {label}: {message}")


def make_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    short = uuid.uuid4().hex[:8]
    return f"MEM-{stamp}-{short}"


def normalize_tags(values: List[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        for part in value.split(","):
            tag = part.strip()
            if tag and tag not in result:
                result.append(tag)
    return result


def make_title(text: str, explicit_title: Optional[str]) -> str:
    if explicit_title:
        return explicit_title.strip()
    line = " ".join(text.strip().split())
    return line[:80] if line else "Untitled memory"


def memory_path(record_id: str) -> Path:
    return MEMORY_DIR / f"{record_id}.json"


def save_memory(text: str, title: Optional[str], kind: str, tags: List[str], source: str) -> Path:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    normalized_tags = normalize_tags(tags)
    for tag in [f"kind:{kind}", f"source:{source}", "user-approved"]:
        if tag not in normalized_tags:
            normalized_tags.append(tag)

    now = datetime.now()
    record = MemoryRecord(
        id=make_id(),
        title=make_title(text, title),
        category="memory",
        content=text,
        tags=normalized_tags,
        status="active",
        source_session=source,
        created=now,
        updated=now,
    )

    path = memory_path(record.id)
    path.write_text(
        json.dumps(record.to_json_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def load_memories() -> List[MemoryRecord]:
    records: List[MemoryRecord] = []
    if not MEMORY_DIR.exists():
        return records

    for path in sorted(MEMORY_DIR.glob("MEM-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            records.append(MemoryRecord.from_json_dict(data))
        except Exception as exc:
            status("Memory Load", f"skipped {path}: {exc}", ok=False)

    return records


def print_memory(record: MemoryRecord, full: bool = False) -> None:
    print(f"- {record.id}")
    print(f"  Title : {record.title}")
    print(f"  Tags  : {', '.join(record.tags) if record.tags else '-'}")
    print(f"  Source: {record.source_session or '-'}")
    if full:
        print("  Text  :")
        for line in record.content.splitlines():
            print(f"    {line}")
    else:
        snippet = " ".join(record.content.split())
        print(f"  Text  : {snippet[:120]}")



def memory_list_payload() -> dict:
    items = []
    errors = []

    if MEMORY_DIR.exists():
        for path in sorted(MEMORY_DIR.glob("MEM-*.json")):
            try:
                data = json.loads(
                    path.read_text(encoding="utf-8")
                )
                record = MemoryRecord.from_json_dict(data)

                items.append({
                    "id": record.id,
                    "title": record.title,
                    "status": record.status,
                    "category": record.category,
                    "chars": len(record.content),
                    "preview": " ".join(
                        record.content.split()
                    )[:120],
                    "tags": list(record.tags),
                    "source": record.source_session,
                    "created": record.created.isoformat(),
                    "updated": record.updated.isoformat(),
                })
            except Exception as exc:
                errors.append({
                    "file": path.name,
                    "error": str(exc),
                })

    return {
        "schema_version": "memory-list-v0.1",
        "count": len(items),
        "items": items,
        "errors": errors,
    }


def trash_list_payload() -> dict:
    items = []
    errors = []

    if MEMORY_TRASH_DIR.exists():
        for path in sorted(
            MEMORY_TRASH_DIR.glob("MEM-*.json")
        ):
            try:
                data = json.loads(
                    path.read_text(encoding="utf-8")
                )
                content = str(
                    data.get("content")
                    or data.get("text")
                    or ""
                )
                metadata = (
                    data.get("metadata")
                    if isinstance(data.get("metadata"), dict)
                    else {}
                )
                title = str(
                    data.get("title")
                    or content[:100]
                    or path.stem
                ).replace("\n", " ")

                items.append({
                    "id": path.stem,
                    "title": title,
                    "status": str(
                        data.get("status")
                        or data.get("lifecycle_state")
                        or "trashed"
                    ),
                    "chars": len(content),
                    "preview": " ".join(
                        content.split()
                    )[:120],
                    "reason": str(
                        metadata.get("trashed_reason")
                        or "-"
                    ),
                    "trashed_at": metadata.get(
                        "trashed_at"
                    ),
                })
            except Exception as exc:
                errors.append({
                    "file": path.name,
                    "error": str(exc),
                })

    return {
        "schema_version": "memory-trash-list-v0.1",
        "count": len(items),
        "items": items,
        "errors": errors,
    }


def resolve_memory_ref(memory_ref: str) -> Path:
    ref = str(memory_ref or "").strip()

    if len(ref) < 5:
        raise ValueError("memory id/suffix must be at least 5 characters")

    files = sorted(MEMORY_DIR.glob("MEM-*.json"))

    exact = [path for path in files if path.stem == ref]
    if len(exact) == 1:
        return exact[0]

    matches = [path for path in files if path.stem.endswith(ref)]

    if not matches:
        raise FileNotFoundError(f"no memory matches suffix/id: {ref}")

    if len(matches) > 1:
        ids = ", ".join(path.stem for path in matches[:10])
        raise ValueError(f"memory suffix is not unique: {ref}; matches: {ids}")

    return matches[0]


def read_memory_record(memory_ref: str) -> tuple[MemoryRecord, Path]:
    path = resolve_memory_ref(memory_ref)
    data = json.loads(path.read_text(encoding="utf-8"))
    return MemoryRecord.from_json_dict(data), path


def write_memory_record(record: MemoryRecord, path: Path) -> None:
    record.updated = datetime.now()
    path.write_text(
        json.dumps(record.to_json_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def set_memory_status(memory_ref: str, new_status: str) -> int:
    if new_status not in VALID_MEMORY_STATUSES:
        status("Memory Lifecycle", f"invalid status: {new_status}", ok=False)
        return 2

    try:
        record, path = read_memory_record(memory_ref)
    except Exception as exc:
        status("Memory Lifecycle", str(exc), ok=False)
        return 2

    old_status = record.status
    record.status = new_status
    write_memory_record(record, path)

    status("Memory", record.id, ok=True)
    status("Status", f"{old_status} -> {new_status}", ok=True)
    status("Policy", "MEM-* file was not deleted. Retrieval uses active memories only.", ok=True)
    return 0



def read_json_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_file(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def find_candidate_promoted_to(memory_id: str) -> tuple[Path | None, str | None]:
    """Find exactly one CAND-* review file that promoted to the given MEM-* id."""
    if not CANDIDATE_DIR.exists():
        return None, f"candidate directory not found: {CANDIDATE_DIR}"

    matches: list[Path] = []

    for path in sorted(CANDIDATE_DIR.glob("CAND-*.json")):
        try:
            data = read_json_file(path)
        except Exception:
            continue

        if data.get("promoted_to") == memory_id:
            matches.append(path)

    if not matches:
        return None, f"no CAND-* with promoted_to={memory_id} found"

    if len(matches) > 1:
        ids = ", ".join(path.stem for path in matches[:10])
        return None, f"multiple CAND-* files point to {memory_id}: {ids}"

    return matches[0], None


def command_undo(args: argparse.Namespace) -> int:
    """Move a MEM-* out of durable memory and return its source CAND-* to review.

    Safety:
    - No hard delete.
    - MEM-* is moved to memory_trash.
    - CAND-* becomes candidate again.
    - promoted_to/promoted_at are removed so it can be reviewed and promoted again.
    """
    confirm = str(args.confirm or "").strip()

    if len(confirm) < 5:
        status("MEM Undo", "confirmation suffix must be at least 5 characters", ok=False)
        return 2

    try:
        memory_path_value = resolve_memory_ref(args.memory_id)
    except Exception as exc:
        status("MEM Undo", str(exc), ok=False)
        return 2

    memory_id = memory_path_value.stem

    if not memory_id.endswith(confirm):
        status("MEM Undo", "confirmation suffix does not match MEM-* id", ok=False)
        status("Memory", memory_id, ok=None)
        return 2

    candidate_path_value, error = find_candidate_promoted_to(memory_id)
    if error:
        status("MEM Undo", error, ok=False)
        return 2

    MEMORY_TRASH_DIR.mkdir(parents=True, exist_ok=True)
    trash_path = MEMORY_TRASH_DIR / memory_path_value.name

    if trash_path.exists():
        status("MEM Undo", f"trash target already exists: {trash_path}", ok=False)
        return 2

    now = datetime.now().isoformat()

    try:
        memory_data = read_json_file(memory_path_value)
        candidate_data = read_json_file(candidate_path_value)
    except Exception as exc:
        status("MEM Undo", f"failed to read MEM/CAND json: {exc}", ok=False)
        return 2

    old_candidate_state = candidate_data.get("state")
    old_memory_status = memory_data.get("status")

    metadata = candidate_data.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    metadata["rollback_from_mem"] = memory_id
    metadata["rollback_at"] = now
    metadata["previous_candidate_state"] = old_candidate_state
    metadata["previous_promoted_to"] = candidate_data.get("promoted_to")
    candidate_data["metadata"] = metadata

    candidate_data["state"] = "candidate"
    candidate_data.pop("promoted_to", None)
    candidate_data.pop("promoted_at", None)
    candidate_data["updated_at"] = now

    memory_metadata = memory_data.get("metadata")
    if not isinstance(memory_metadata, dict):
        memory_metadata = {}

    memory_metadata["trashed_reason"] = "rollback_to_candidate"
    memory_metadata["rollback_candidate_id"] = candidate_data.get("id") or candidate_path_value.stem
    memory_metadata["trashed_at"] = now
    memory_metadata["previous_status"] = old_memory_status
    memory_data["metadata"] = memory_metadata
    memory_data["status"] = "trashed"
    memory_data["lifecycle_state"] = "trashed"
    memory_data["updated"] = now

    write_json_file(candidate_path_value, candidate_data)
    write_json_file(memory_path_value, memory_data)
    shutil.move(str(memory_path_value), str(trash_path))

    status("MEM Undo", memory_id, ok=True)
    status("Candidate", f"{candidate_path_value.stem}: {old_candidate_state} -> candidate", ok=True)
    status("Memory Trash", str(trash_path), ok=True)
    status("Policy", "MEM-* was moved to trash, not hard-deleted. CAND-* returned to review.", ok=True)
    return 0



def trash_memory_file(memory_path_value: Path, reason: str) -> tuple[bool, str]:
    """Move one MEM-* file from active memory to memory_trash.

    No hard delete. Trash lives next to MEMORY_DIR on the MEMORIA storage root.
    """
    MEMORY_TRASH_DIR.mkdir(parents=True, exist_ok=True)
    trash_path = MEMORY_TRASH_DIR / memory_path_value.name

    if trash_path.exists():
        return False, f"trash target already exists: {trash_path}"

    try:
        memory_data = read_json_file(memory_path_value)
    except Exception as exc:
        return False, f"failed to read memory json: {exc}"

    now = datetime.now().isoformat()
    old_status = memory_data.get("status") or memory_data.get("lifecycle_state") or "active"

    memory_metadata = memory_data.get("metadata")
    if not isinstance(memory_metadata, dict):
        memory_metadata = {}

    memory_metadata["trashed_reason"] = reason
    memory_metadata["trashed_at"] = now
    memory_metadata["previous_status"] = old_status

    memory_data["metadata"] = memory_metadata
    memory_data["status"] = "trashed"
    memory_data["lifecycle_state"] = "trashed"
    memory_data["updated"] = now

    write_json_file(memory_path_value, memory_data)
    shutil.move(str(memory_path_value), str(trash_path))
    return True, str(trash_path)


def resolve_trash_ref(memory_ref: str) -> Path:
    ref = str(memory_ref or "").strip()

    if len(ref) < 5:
        raise ValueError("trash memory id/suffix must be at least 5 characters")

    files = sorted(MEMORY_TRASH_DIR.glob("MEM-*.json"))

    exact = [path for path in files if path.stem == ref]
    if len(exact) == 1:
        return exact[0]

    matches = [path for path in files if path.stem.endswith(ref)]

    if not matches:
        raise FileNotFoundError(f"no trashed memory matches suffix/id: {ref}")

    if len(matches) > 1:
        ids = ", ".join(path.stem for path in matches[:10])
        raise ValueError(f"trash memory suffix is not unique: {ref}; matches: {ids}")

    return matches[0]


def print_trash_item(path: Path) -> None:
    try:
        data = read_json_file(path)
    except Exception as exc:
        status("Trash Load", f"skipped {path.name}: {exc}", ok=False)
        return

    text = str(data.get("content") or data.get("text") or "")
    title = str(data.get("title") or text[:100]).replace("\n", " ")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}

    print(
        f"{path.stem} | status={data.get('status')} | chars={len(text)} | "
        f"reason={metadata.get('trashed_reason', '-')} | {title[:140]}"
    )


def command_trash(args: argparse.Namespace) -> int:
    confirm = str(args.confirm or "").strip()

    if len(confirm) < 5:
        status("Memory Trash", "confirmation suffix must be at least 5 characters", ok=False)
        return 2

    try:
        memory_path_value = resolve_memory_ref(args.memory_id)
    except Exception as exc:
        status("Memory Trash", str(exc), ok=False)
        return 2

    memory_id = memory_path_value.stem

    if not memory_id.endswith(confirm):
        status("Memory Trash", "confirmation suffix does not match MEM-* id", ok=False)
        status("Memory", memory_id, ok=None)
        return 2

    ok, message = trash_memory_file(memory_path_value, "manual_trash")
    if not ok:
        status("Memory Trash", message, ok=False)
        return 2

    status("Memory Trash", memory_id, ok=True)
    status("Trash Path", message, ok=True)
    status("Policy", "MEM-* moved to trash, not hard-deleted.", ok=True)
    return 0


def command_trash_disabled(args: argparse.Namespace) -> int:
    if args.confirm != "TRASH-DISABLED-MEMORIES":
        status("Memory Trash Disabled", "confirmation must be exactly TRASH-DISABLED-MEMORIES", ok=False)
        return 2

    moved = 0
    skipped = 0

    for path in sorted(MEMORY_DIR.glob("MEM-*.json")):
        try:
            data = read_json_file(path)
        except Exception as exc:
            status("Memory Trash Disabled", f"skipped {path.name}: {exc}", ok=False)
            skipped += 1
            continue

        lifecycle = str(data.get("status") or data.get("lifecycle_state") or "active").lower()

        if lifecycle != "disabled":
            skipped += 1
            continue

        ok, message = trash_memory_file(path, "trash_disabled_bulk")
        if ok:
            moved += 1
            status("Trashed", f"{path.stem} -> {message}", ok=True)
        else:
            skipped += 1
            status("Trash Failed", f"{path.stem}: {message}", ok=False)

    status("Memory Trash Disabled", f"moved={moved}, skipped={skipped}", ok=True)
    status("Policy", "Only disabled MEM-* files were moved. No hard delete.", ok=True)
    return 0


def command_trash_list(args: argparse.Namespace) -> int:
    if getattr(args, "json", False):
        print(json.dumps(
            trash_list_payload(),
            ensure_ascii=False,
            sort_keys=True,
        ))
        return 0

    if not MEMORY_TRASH_DIR.exists():
        status("Memory Trash", "empty / trash directory not found", ok=None)
        return 0

    items = sorted(MEMORY_TRASH_DIR.glob("MEM-*.json"))

    if not items:
        status("Memory Trash", "empty", ok=None)
        return 0

    status("Memory Trash", f"{len(items)} item(s)", ok=True)

    for path in items:
        print_trash_item(path)

    return 0


def command_purge(args: argparse.Namespace) -> int:
    confirm = str(args.confirm or "").strip()

    if len(confirm) < 5:
        status("Memory Purge", "confirmation suffix must be at least 5 characters", ok=False)
        return 2

    try:
        trash_path = resolve_trash_ref(args.memory_id)
    except Exception as exc:
        status("Memory Purge", str(exc), ok=False)
        return 2

    memory_id = trash_path.stem

    if not memory_id.endswith(confirm):
        status("Memory Purge", "confirmation suffix does not match trashed MEM-* id", ok=False)
        status("Memory", memory_id, ok=None)
        return 2

    trash_path.unlink()

    status("Memory Purge", memory_id, ok=True)
    status("Policy", "Only a MEM-* file already in memory_trash was permanently deleted.", ok=True)
    return 0


def command_purge_all(args: argparse.Namespace) -> int:
    if args.confirm != "PURGE-ALL-MEMORY-TRASH":
        status("Memory Purge All", "confirmation must be exactly PURGE-ALL-MEMORY-TRASH", ok=False)
        return 2

    if not MEMORY_TRASH_DIR.exists():
        status("Memory Purge All", "trash directory not found", ok=None)
        return 0

    purged = 0

    for path in sorted(MEMORY_TRASH_DIR.glob("MEM-*.json")):
        path.unlink()
        purged += 1

    status("Memory Purge All", f"purged={purged}", ok=True)
    status("Policy", "Only MEM-* files already in memory_trash were permanently deleted.", ok=True)
    return 0


def command_show(args: argparse.Namespace) -> int:
    try:
        record, _path = read_memory_record(args.memory_id)
    except Exception as exc:
        status("Memory Show", str(exc), ok=False)
        return 2

    print_memory(record, full=True)
    return 0


def command_enable(args: argparse.Namespace) -> int:
    return set_memory_status(args.memory_id, "active")


def command_disable(args: argparse.Namespace) -> int:
    return set_memory_status(args.memory_id, "disabled")


def command_archive(args: argparse.Namespace) -> int:
    return set_memory_status(args.memory_id, "archived")


def command_add(args: argparse.Namespace) -> int:
    path = save_memory(
        text=args.text,
        title=args.title,
        kind=args.kind,
        tags=args.tag,
        source=args.source,
    )
    status("Memory Added", str(path), ok=True)
    status("Policy", "manual user-approved memory only; no automatic scan", ok=True)
    return 0


def command_list(args: argparse.Namespace) -> int:
    if getattr(args, "json", False):
        print(json.dumps(
            memory_list_payload(),
            ensure_ascii=False,
            sort_keys=True,
        ))
        return 0

    records = load_memories()
    if not records:
        status("Memories", "none found", ok=None)
        return 0

    status("Memories", f"{len(records)} found", ok=True)
    for record in records:
        print_memory(record, full=args.full)
    return 0


def command_search(args: argparse.Namespace) -> int:
    query = args.query.lower()
    matches = []

    for record in load_memories():
        haystack = " ".join(
            [record.title, record.content, " ".join(record.tags), record.source_session or ""]
        ).lower()
        if query in haystack:
            matches.append(record)

    if not matches:
        status("Search", "no matching memories found", ok=None)
        return 0

    status("Search", f"{len(matches)} matching memories found", ok=True)
    for record in matches:
        print_memory(record, full=args.full)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual user-approved MEMORIA memory store.")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="Add a manually approved memory.")
    add.add_argument("--text", required=True, help="Memory text to store.")
    add.add_argument("--title", default=None, help="Optional memory title.")
    add.add_argument("--kind", default="note", help="Memory kind, e.g. principle, adr-note.")
    add.add_argument("--tag", action="append", default=[], help="Tag. Can be repeated or comma-separated.")
    add.add_argument("--source", default="manual", help="Source label. Default: manual.")
    add.set_defaults(func=command_add)

    list_cmd = sub.add_parser("list", help="List stored memories.")
    list_cmd.add_argument("--full", action="store_true", help="Print full memory text.")
    list_cmd.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable summaries without full text.",
    )
    list_cmd.set_defaults(func=command_list)

    search = sub.add_parser("search", help="Search stored memories.")
    search.add_argument("query", help="Search query.")
    search.add_argument("--full", action="store_true", help="Print full memory text.")
    search.set_defaults(func=command_search)

    show = sub.add_parser("show", help="Show one stored memory by full ID or unique suffix.")
    show.add_argument("memory_id", help="Full MEM-* id or unique suffix, minimum 5 characters.")
    show.set_defaults(func=command_show)

    enable = sub.add_parser("enable", help="Enable a stored memory for retrieval.")
    enable.add_argument("memory_id", help="Full MEM-* id or unique suffix, minimum 5 characters.")
    enable.set_defaults(func=command_enable)

    disable = sub.add_parser("disable", help="Disable a stored memory so retrieval ignores it.")
    disable.add_argument("memory_id", help="Full MEM-* id or unique suffix, minimum 5 characters.")
    disable.set_defaults(func=command_disable)

    archive = sub.add_parser("archive", help="Archive a stored memory so retrieval ignores it.")
    archive.add_argument("memory_id", help="Full MEM-* id or unique suffix, minimum 5 characters.")
    archive.set_defaults(func=command_archive)

    undo = sub.add_parser("undo", help="Move MEM-* to trash and return its source CAND-* to review.")
    undo.add_argument("memory_id", help="Full MEM-* id or unique suffix, minimum 5 characters.")
    undo.add_argument("--confirm", required=True, help="Repeat the last 5+ characters of the MEM-* id.")
    undo.set_defaults(func=command_undo)

    trash = sub.add_parser("trash", help="Move one MEM-* to memory_trash without hard delete.")
    trash.add_argument("memory_id", help="Full MEM-* id or unique suffix, minimum 5 characters.")
    trash.add_argument("--confirm", required=True, help="Repeat the last 5+ characters of the MEM-* id.")
    trash.set_defaults(func=command_trash)

    trash_disabled = sub.add_parser("trash-disabled", help="Move all disabled MEM-* files to memory_trash.")
    trash_disabled.add_argument("--confirm", required=True, help="Must be exactly TRASH-DISABLED-MEMORIES.")
    trash_disabled.set_defaults(func=command_trash_disabled)

    trash_list = sub.add_parser("trash-list", help="List MEM-* files in memory_trash without full text.")
    trash_list.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable summaries without full text.",
    )
    trash_list.set_defaults(func=command_trash_list)

    purge = sub.add_parser("purge", help="Permanently delete one MEM-* file from memory_trash only.")
    purge.add_argument("memory_id", help="Full MEM-* id or unique suffix in memory_trash, minimum 5 characters.")
    purge.add_argument("--confirm", required=True, help="Repeat the last 5+ characters of the trashed MEM-* id.")
    purge.set_defaults(func=command_purge)

    purge_all = sub.add_parser("purge-all", help="Permanently delete all MEM-* files from memory_trash only.")
    purge_all.add_argument("--confirm", required=True, help="Must be exactly PURGE-ALL-MEMORY-TRASH.")
    purge_all.set_defaults(func=command_purge_all)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not getattr(args, "json", False):
        print("MEMORIA MEMORY STORE V0.1")
        print(
            "Manual user-approved memory only. "
            "No automatic scans. "
            "No private directory backup."
        )
        print()

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
