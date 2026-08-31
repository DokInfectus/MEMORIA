#!/usr/bin/env python3
from __future__ import annotations

# MEMORIA runtime guard: central mode enforcement.
import sys as _memoria_runtime_sys
from pathlib import Path as _MemoriaRuntimePath

_MEMORIA_TOOLS_DIR = _MemoriaRuntimePath(__file__).resolve().parent
if str(_MEMORIA_TOOLS_DIR) not in _memoria_runtime_sys.path:
    _memoria_runtime_sys.path.insert(0, str(_MEMORIA_TOOLS_DIR))

from memoria_runtime_guard import require_capability as _memoria_require_capability

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
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from memoria_storage_paths import managed_path as _memoria_managed_path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_DIR = _memoria_managed_path(
    "memory_candidates",
    "MEMORIA_CANDIDATE_DIR",
    "knowledge/memory_candidates",
)

VALID_LAYERS = ("core", "user", "project", "session")
VALID_STATES = ("candidate", "user-approved", "rejected", "archived")

SENSITIVE_PATTERNS = (
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "possible API key"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE), "possible bearer token"),
    (re.compile(r"\b(api[_ -]?key|password|passwd|secret|token)\b\s*[:=]", re.IGNORECASE), "secret-like assignment"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_store() -> None:
    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)


def normalize_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    result: list[str] = []
    for item in raw.split(","):
        tag = item.strip().lower()
        tag = re.sub(r"[^a-z0-9_.:-]+", "-", tag)
        tag = tag.strip("-")
        if tag and tag not in result:
            result.append(tag)
    return result[:20]


def scan_for_sensitive_content(
    title: str,
    text: str,
    tags: list[str],
    metadata: dict | None = None,
) -> list[str]:
    metadata_text = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
    joined = "\n".join([title, text, ",".join(tags), metadata_text])
    warnings: list[str] = []
    for pattern, label in SENSITIVE_PATTERNS:
        if pattern.search(joined):
            warnings.append(label)
    return warnings


def parse_metadata_json(raw: str | None) -> dict:
    if not raw:
        return {}

    try:
        data = json.loads(raw)
    except Exception as e:
        raise ValueError(f"invalid metadata json: {e}")

    if not isinstance(data, dict):
        raise ValueError("metadata json must be an object")

    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True)
    if len(encoded) > 10000:
        raise ValueError("metadata json is too large")

    return data


def candidate_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"CAND-{stamp}-{suffix}"


def path_for(candidate_id_value: str) -> Path:
    if not re.fullmatch(r"CAND-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}", candidate_id_value):
        raise ValueError("invalid candidate id")
    return CANDIDATE_DIR / f"{candidate_id_value}.json"


def write_candidate(data: dict) -> None:
    ensure_store()
    path = path_for(data["id"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_candidate(candidate_id_value: str) -> dict:
    path = path_for(candidate_id_value)
    if not path.exists():
        raise FileNotFoundError(candidate_id_value)
    return json.loads(path.read_text(encoding="utf-8"))



def read_json_object(
    path: Path,
    label: str,
) -> dict:
    if path.is_symlink():
        raise ValueError(
            f"{label} must not be a symbolic link"
        )

    if not path.is_file():
        raise ValueError(
            f"{label} is not a regular file: {path}"
        )

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise ValueError(
            f"invalid {label} JSON: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"{label} JSON must be an object"
        )

    return data


def write_json_atomic_file(
    path: Path,
    data: dict,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_name(
        path.name
        + ".tmp-"
        + uuid.uuid4().hex
    )

    try:
        with temporary.open(
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump(
                data,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(
            temporary,
            path,
        )

    finally:
        if temporary.exists():
            temporary.unlink()


def candidate_file_snapshot(
    path: Path,
) -> dict:
    if path.is_symlink():
        raise ValueError(
            f"candidate file is a symbolic link: {path.name}"
        )

    if not path.is_file():
        raise ValueError(
            f"candidate file is missing: {path.name}"
        )

    raw = path.read_bytes()

    try:
        data = json.loads(
            raw.decode("utf-8")
        )
    except Exception as exc:
        raise ValueError(
            f"candidate JSON is invalid: {path.name}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"candidate JSON is not an object: {path.name}"
        )

    candidate_id_value = path.stem

    if data.get("id") != candidate_id_value:
        raise ValueError(
            f"candidate id/path mismatch: {candidate_id_value}"
        )

    return {
        "id": candidate_id_value,
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "state": str(data.get("state") or ""),
        "title": " ".join(
            str(data.get("title") or "").split()
        ),
        "updated_at": data.get("updated_at"),
    }


def candidate_ids_from_manifest(
    manifest: dict,
) -> tuple[list[str], list[dict]]:
    items = manifest.get("candidates")

    if not isinstance(items, list):
        raise ValueError(
            "selection manifest must contain a candidates list"
        )

    if len(items) > 10000:
        raise ValueError(
            "selection manifest exceeds 10000 entries"
        )

    candidate_ids: list[str] = []
    skipped: list[dict] = []
    seen: set[str] = set()

    for index, item in enumerate(
        items,
        start=1,
    ):
        if isinstance(item, dict):
            raw_id = item.get("id")
        elif isinstance(item, str):
            raw_id = item
        else:
            raw_id = None

        candidate_id_value = str(
            raw_id or ""
        ).strip()

        if not candidate_id_value:
            skipped.append({
                "input_index": index,
                "id": None,
                "reason": "missing candidate id",
            })
            continue

        try:
            path_for(candidate_id_value)
        except ValueError:
            skipped.append({
                "input_index": index,
                "id": candidate_id_value,
                "reason": "invalid CAND-* id",
            })
            continue

        if candidate_id_value in seen:
            skipped.append({
                "input_index": index,
                "id": candidate_id_value,
                "reason": "duplicate selection",
            })
            continue

        seen.add(candidate_id_value)
        candidate_ids.append(
            candidate_id_value
        )

    return candidate_ids, skipped


def iter_candidates() -> list[dict]:
    ensure_store()
    items: list[dict] = []
    for path in sorted(CANDIDATE_DIR.glob("CAND-*.json")):
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return items


def command_create(args: argparse.Namespace) -> int:
    title = (args.title or "").strip()
    text = (args.text or "").strip()

    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8").strip()

    if not title:
        print("FAIL Memory Candidate: title is required")
        return 2

    if not text:
        print("FAIL Memory Candidate: text is required")
        return 2

    if args.layer not in VALID_LAYERS:
        print(f"FAIL Memory Candidate: invalid layer {args.layer!r}")
        return 2

    tags = normalize_tags(args.tags)

    try:
        metadata = parse_metadata_json(args.metadata_json)
    except ValueError as e:
        print(f"FAIL Memory Candidate: {e}")
        return 2

    warnings = scan_for_sensitive_content(title, text, tags, metadata)

    _memoria_require_capability("candidate_creation_enabled")
    _memoria_require_storage_watchdog_ok()
    print("## MEMORIA MEMORY CANDIDATE CREATE V0.1")
    print("------------------------------------------------------------")
    print("No automatic durable memory write.")
    print("Token value is never printed.")
    print("Private chat logs are not scanned.")
    print()

    if warnings:
        print("BLOCKED Memory Candidate: possible sensitive content detected")
        for warning in warnings:
            print(f"WARN {warning}")
        print("OK   Result: candidate was not stored")
        return 2

    now = utc_now()
    data = {
        "schema_version": "memory-candidate-v0.1",
        "id": candidate_id(),
        "state": "candidate",
        "layer": args.layer,
        "title": title,
        "text": text,
        "tags": tags,
        "source": args.source,
        "metadata": metadata,
        "created_at": now,
        "updated_at": now,
        "safety": {
            "sensitive_scan": "passed",
            "warnings": [],
        },
    }

    write_candidate(data)

    print(f"OK   Candidate: {data['id']}")
    print(f"OK   State: {data['state']}")
    print(f"OK   Layer: {data['layer']}")
    print(f"OK   Title: {data['title']}")
    print("OK   Result: candidate stored for user review")
    return 0


def resolve_candidate_ref(candidate_ref: str) -> tuple[Path | None, str | None]:
    """Resolve a CAND-* id or a unique id suffix to a candidate file."""
    ref = str(candidate_ref or "").strip()

    if not ref:
        return None, "empty candidate id"

    if len(ref) < 5:
        return None, "candidate id/suffix must be at least 5 characters"

    files = sorted(CANDIDATE_DIR.glob("CAND-*.json"))

    exact = [path for path in files if path.stem == ref]
    if len(exact) == 1:
        return exact[0], None

    matches = [path for path in files if path.stem.endswith(ref)]

    if not matches:
        return None, f"no candidate matches suffix/id: {ref}"

    if len(matches) > 1:
        ids = ", ".join(path.stem for path in matches[:10])
        return None, f"candidate suffix is not unique: {ref}; matches: {ids}"

    return matches[0], None


def command_delete(args: argparse.Namespace) -> int:
    """Delete a candidate from the review pool after explicit short confirmation.

    This only applies to CAND-* review files. Durable MEM-* files are not handled here.
    """
    candidate_ref = str(args.candidate_id or "").strip()
    confirm = str(args.confirm or "").strip()

    if len(confirm) < 5:
        print("ERROR delete confirmation must contain at least the last 5 id characters")
        return 2

    path, error = resolve_candidate_ref(candidate_ref)
    if error:
        print(f"ERROR {error}")
        return 2

    candidate_id = path.stem

    if not candidate_id.endswith(confirm):
        print("ERROR confirmation does not match candidate id suffix")
        print(f"Candidate: {candidate_id}")
        return 2

    path.unlink()
    print(f"OK deleted candidate: {candidate_id}")
    print("Policy: only CAND-* review file was deleted. Durable MEM-* was not touched.")
    return 0



def command_prepare_delete_batch(
    args: argparse.Namespace,
) -> int:
    """Create an immutable candidate deletion plan.

    The explicitly selected manifest is read only. No CAND-*,
    MEM-* or attachment object is changed by this command.
    """
    manifest_path = Path(
        args.manifest
    ).expanduser().resolve()

    output_path = Path(
        args.output
    ).expanduser().resolve()

    if output_path.exists():
        print(
            "ERROR delete plan output already exists; "
            "refusing overwrite"
        )
        print(f"Path: {output_path}")
        return 2

    try:
        manifest = read_json_object(
            manifest_path,
            "selection manifest",
        )
        candidate_ids, skipped = (
            candidate_ids_from_manifest(
                manifest
            )
        )
    except ValueError as exc:
        print(f"ERROR {exc}")
        return 2

    entries: list[dict] = []

    for candidate_id_value in candidate_ids:
        try:
            candidate_path = path_for(
                candidate_id_value
            )

            snapshot = candidate_file_snapshot(
                candidate_path
            )

            if snapshot["state"] != "candidate":
                skipped.append({
                    "id": candidate_id_value,
                    "reason": (
                        "state is not candidate: "
                        f"{snapshot['state'] or 'missing'}"
                    ),
                })
                continue

            entries.append({
                "id": snapshot["id"],
                "sha256": snapshot["sha256"],
                "size_bytes":
                    snapshot["size_bytes"],
                "state": snapshot["state"],
                "title": snapshot["title"],
                "updated_at":
                    snapshot["updated_at"],
            })

        except ValueError as exc:
            skipped.append({
                "id": candidate_id_value,
                "reason": str(exc),
            })

    if not entries:
        print(
            "ERROR no open candidates are eligible "
            "for the delete plan"
        )
        print(
            f"Skipped: {len(skipped)}"
        )
        return 2

    plan = {
        "schema_version":
            "memory-candidate-delete-plan-v0.1",
        "created_at": utc_now(),
        "candidate_root": str(
            CANDIDATE_DIR.expanduser().resolve()
        ),
        "source_manifest": str(
            manifest_path
        ),
        "selected_count": len(entries),
        "entries": entries,
        "skipped_count": len(skipped),
        "skipped": skipped,
        "policy": {
            "candidate_state_required":
                "candidate",
            "durable_memories_touched":
                False,
            "approved_candidates_touched":
                False,
            "archived_candidates_touched":
                False,
            "file_hashes_fixed_before_confirmation":
                True,
            "explicit_batch_confirmation_required":
                True,
        },
    }

    write_json_atomic_file(
        output_path,
        plan,
    )

    print(
        "## MEMORIA CANDIDATE DELETE PLAN V0.1"
    )
    print("-" * 60)
    print(f"Selection manifest: {manifest_path}")
    print(f"Delete plan: {output_path}")
    print(f"Selected open candidates: {len(entries)}")
    print(f"Skipped entries: {len(skipped)}")
    print()

    for index, entry in enumerate(
        entries,
        start=1,
    ):
        title = entry.get("title") or "(ohne Titel)"

        print(
            f"{index:03d} | {entry['id']} | "
            f"{title[:100]}"
        )

    if skipped:
        print()
        print("Skipped:")

        for item in skipped:
            print(
                f"- {item.get('id') or '(no id)'} | "
                f"{item.get('reason')}"
            )

    print()
    print(
        "No Candidate was deleted. "
        "No durable MEM-* was touched."
    )
    print(
        "Required confirmation for deletion: "
        f"LÖSCHEN {len(entries)}"
    )

    return 0


def command_delete_batch(
    args: argparse.Namespace,
) -> int:
    """Delete exactly the candidates fixed in a verified plan."""
    plan_path = Path(
        args.plan
    ).expanduser().resolve()

    try:
        plan = read_json_object(
            plan_path,
            "delete plan",
        )
    except ValueError as exc:
        print(f"ERROR {exc}")
        return 2

    if (
        plan.get("schema_version")
        != "memory-candidate-delete-plan-v0.1"
    ):
        print(
            "ERROR unsupported candidate delete plan schema"
        )
        return 2

    expected_root = str(
        CANDIDATE_DIR.expanduser().resolve()
    )

    if plan.get("candidate_root") != expected_root:
        print(
            "ERROR delete plan belongs to a different "
            "Candidate Store"
        )
        print(
            f"Plan root: {plan.get('candidate_root')}"
        )
        print(f"Current root: {expected_root}")
        return 2

    entries = plan.get("entries")

    if not isinstance(entries, list):
        print(
            "ERROR delete plan entries must be a list"
        )
        return 2

    declared_count = plan.get(
        "selected_count"
    )

    if (
        not isinstance(declared_count, int)
        or declared_count != len(entries)
        or declared_count < 1
        or declared_count > 10000
    ):
        print(
            "ERROR delete plan count is invalid"
        )
        return 2

    required_confirmation = (
        f"LÖSCHEN {declared_count}"
    )

    confirmation = str(
        args.confirm or ""
    ).strip()

    if confirmation != required_confirmation:
        print(
            "ERROR batch deletion confirmation "
            "does not match"
        )
        print(
            f"Required: {required_confirmation}"
        )
        print(
            "No Candidate was deleted."
        )
        return 2

    preflight: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()

    for entry in entries:
        if not isinstance(entry, dict):
            errors.append(
                "delete plan contains a non-object entry"
            )
            continue

        candidate_id_value = str(
            entry.get("id") or ""
        ).strip()

        expected_hash = str(
            entry.get("sha256") or ""
        ).strip()

        if candidate_id_value in seen:
            errors.append(
                f"duplicate plan id: {candidate_id_value}"
            )
            continue

        seen.add(candidate_id_value)

        try:
            candidate_path = path_for(
                candidate_id_value
            )

            snapshot = candidate_file_snapshot(
                candidate_path
            )

        except ValueError as exc:
            errors.append(str(exc))
            continue

        if snapshot["state"] != "candidate":
            errors.append(
                f"{candidate_id_value}: state changed to "
                f"{snapshot['state'] or 'missing'}"
            )
            continue

        if not re.fullmatch(
            r"[a-f0-9]{64}",
            expected_hash,
        ):
            errors.append(
                f"{candidate_id_value}: invalid planned SHA-256"
            )
            continue

        if snapshot["sha256"] != expected_hash:
            errors.append(
                f"{candidate_id_value}: file changed "
                "after delete plan creation"
            )
            continue

        preflight.append({
            **snapshot,
            "expected_sha256":
                expected_hash,
        })

    if errors or len(preflight) != declared_count:
        print(
            "BLOCKED candidate batch deletion"
        )
        print(
            "Reason: delete plan preflight failed"
        )

        for error in errors:
            print(f"- {error}")

        print()
        print(
            "No Candidate was deleted. "
            "No durable MEM-* was touched."
        )
        return 2

    # Complete second verification immediately before staging.
    for item in preflight:
        current = candidate_file_snapshot(
            item["path"]
        )

        if (
            current["state"] != "candidate"
            or current["sha256"]
            != item["expected_sha256"]
        ):
            print(
                "BLOCKED candidate batch deletion"
            )
            print(
                f"Reason: candidate changed before staging: "
                f"{item['id']}"
            )
            print(
                "No Candidate was deleted."
            )
            return 2

    staging_dir = (
        CANDIDATE_DIR
        / (
            ".delete-batch-"
            + uuid.uuid4().hex
        )
    )

    staging_dir.mkdir(
        mode=0o700,
        parents=False,
        exist_ok=False,
    )

    moved: list[tuple[Path, Path]] = []

    try:
        for item in preflight:
            source = item["path"]
            destination = (
                staging_dir / source.name
            )

            os.replace(
                source,
                destination,
            )

            moved.append(
                (source, destination)
            )

    except Exception as exc:
        rollback_errors: list[str] = []

        for source, destination in reversed(
            moved
        ):
            try:
                if destination.exists():
                    os.replace(
                        destination,
                        source,
                    )
            except Exception as rollback_exc:
                rollback_errors.append(
                    f"{source.name}: {rollback_exc}"
                )

        try:
            staging_dir.rmdir()
        except OSError:
            pass

        print(
            "FAIL candidate batch staging"
        )
        print(f"Reason: {exc}")
        print(
            f"Rolled back: "
            f"{len(moved) - len(rollback_errors)}"
        )

        for error in rollback_errors:
            print(f"- Rollback error: {error}")

        return 3

    deleted = 0

    try:
        for _source, destination in moved:
            destination.unlink()
            deleted += 1

        staging_dir.rmdir()

    except Exception as exc:
        print(
            "FAIL candidate batch final deletion"
        )
        print(f"Deleted: {deleted}")
        print(
            f"Recovery directory: {staging_dir}"
        )
        print(f"Reason: {exc}")
        return 3

    print(
        "## MEMORIA CANDIDATE BATCH DELETE V0.1"
    )
    print("-" * 60)
    print(f"Plan: {plan_path}")
    print(f"Confirmed: {required_confirmation}")
    print(f"Deleted candidates: {deleted}")
    print("Skipped during deletion: 0")
    print()
    print(
        "Policy: only the planned state=candidate "
        "CAND-* review files were deleted."
    )
    print(
        "Durable MEM-* was not touched."
    )
    print(
        "Approved, rejected and archived Candidates "
        "were not touched."
    )

    return 0


def command_list(args: argparse.Namespace) -> int:
    print("## MEMORIA MEMORY CANDIDATE LIST V0.1")
    print("------------------------------------------------------------")

    items = iter_candidates()
    if args.state:
        items = [item for item in items if item.get("state") == args.state]

    if not items:
        print("INFO No memory candidates found")
        return 0

    for item in items:
        tags = ",".join(item.get("tags", []))
        print(
            f"{item.get('id')} | {item.get('state')} | {item.get('layer')} | "
            f"{item.get('title')} | tags={tags}"
        )

    return 0


def command_show(args: argparse.Namespace) -> int:
    path, error = resolve_candidate_ref(args.candidate_id)
    if error:
        print(f"ERROR {error}")
        return 2
    item = read_candidate(path.stem)

    print("## MEMORIA MEMORY CANDIDATE SHOW V0.1")
    print("------------------------------------------------------------")
    print(f"ID: {item.get('id')}")
    print(f"State: {item.get('state')}")
    print(f"Layer: {item.get('layer')}")
    print(f"Title: {item.get('title')}")
    print(f"Tags: {', '.join(item.get('tags', []))}")
    if item.get("metadata"):
        print(f"Metadata: {json.dumps(item.get('metadata', {}), ensure_ascii=False, sort_keys=True)}")
    print(f"Created: {item.get('created_at')}")
    print(f"Updated: {item.get('updated_at')}")
    print()
    print("Text:")
    print(item.get("text", ""))
    return 0


def set_state(candidate_id_value: str, new_state: str) -> int:
    if new_state not in VALID_STATES:
        print(f"FAIL Memory Candidate: invalid state {new_state!r}")
        return 2

    path, error = resolve_candidate_ref(candidate_id_value)
    if error:
        print(f"ERROR {error}")
        return 2

    item = read_candidate(path.stem)
    item["state"] = new_state
    item["updated_at"] = utc_now()
    write_candidate(item)

    print("## MEMORIA MEMORY CANDIDATE STATE V0.1")
    print("------------------------------------------------------------")
    print(f"OK   Candidate: {item['id']}")
    print(f"OK   State: {item['state']}")
    print("OK   Result: state updated")
    return 0


def command_approve(args: argparse.Namespace) -> int:
    return set_state(args.candidate_id, "user-approved")


def command_reject(args: argparse.Namespace) -> int:
    return set_state(args.candidate_id, "rejected")


def command_archive(args: argparse.Namespace) -> int:
    return set_state(args.candidate_id, "archived")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MEMORIA memory candidate store")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument("--title", required=True)
    create.add_argument("--text")
    create.add_argument("--text-file")
    create.add_argument("--layer", choices=VALID_LAYERS, default="user")
    create.add_argument("--source", default="manual")
    create.add_argument("--metadata-json", default="")
    create.add_argument("--tags", default="")
    create.set_defaults(func=command_create)

    prepare_delete_batch = sub.add_parser(
        "prepare-delete-batch",
        help=(
            "Prepare a hash-fixed delete plan from an "
            "explicit candidate selection manifest"
        ),
    )
    prepare_delete_batch.add_argument(
        "--manifest",
        required=True,
        help=(
            "Explicit JSON selection manifest containing "
            "a candidates list"
        ),
    )
    prepare_delete_batch.add_argument(
        "--output",
        required=True,
        help="New JSON delete-plan path",
    )
    prepare_delete_batch.set_defaults(
        func=command_prepare_delete_batch
    )

    delete_batch = sub.add_parser(
        "delete-batch",
        help=(
            "Delete exactly the state=candidate entries "
            "fixed in a delete plan"
        ),
    )
    delete_batch.add_argument(
        "--plan",
        required=True,
        help="Hash-fixed candidate delete-plan JSON",
    )
    delete_batch.add_argument(
        "--confirm",
        required=True,
        help="Exact confirmation: LÖSCHEN <count>",
    )
    delete_batch.set_defaults(
        func=command_delete_batch
    )

    list_cmd = sub.add_parser("list")
    list_cmd.add_argument("--state", choices=VALID_STATES)
    list_cmd.set_defaults(func=command_list)

    show = sub.add_parser("show")
    show.add_argument("candidate_id")
    show.set_defaults(func=command_show)

    approve = sub.add_parser("approve")
    approve.add_argument("candidate_id")
    approve.set_defaults(func=command_approve)

    reject = sub.add_parser("reject")
    reject.add_argument("candidate_id")
    reject.set_defaults(func=command_reject)

    archive = sub.add_parser("archive")
    archive.add_argument("candidate_id")
    archive.set_defaults(func=command_archive)

    delete = sub.add_parser("delete")
    delete.add_argument("candidate_id", help="Full CAND-* id or unique suffix, minimum 5 characters")
    delete.add_argument("--confirm", required=True, help="Repeat the last 5+ characters of the candidate id")
    delete.set_defaults(func=command_delete)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except FileNotFoundError as exc:
        print(f"FAIL Memory Candidate: not found {exc}")
        return 2
    except ValueError as exc:
        print(f"FAIL Memory Candidate: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
