#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / "tools"

for entry in (PROJECT_ROOT, TOOLS_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from adapter.factory import build_adapter
from configure.manager import ConfigureManager
from memoria_big_archive_batch_runner import (
    load_json,
    runtime_signature,
    utc_now,
    write_json_atomic,
)
from memoria_big_archive_block_summarizer import (
    apply_output_budget,
    build_schema_retry_prompt,
    extract_json_object,
    normalized_match_text,
    require_local_runtime,
    send_with_final_json_retry,
)
from memoria_big_archive_reducer import (
    BATCH_SCHEMA_VERSION,
    SCHEMA_VERSION as REDUCER_SCHEMA_VERSION,
    sha256_file,
    validate_batch_manifest,
)


GROUP_SCHEMA_VERSION = "big-archive-reducer-group-v0.1"
DEFAULT_CONTEXT_HEADROOM = 4096
DEFAULT_CHARS_PER_TOKEN = 3.0

STRING_LIST_FIELDS = (
    "themes",
    "important_memories",
    "projects_and_decisions",
    "uncertainties",
    "evidence",
)


def validate_reducer_manifest(
    manifest: dict[str, Any],
) -> None:
    if manifest.get("schema_version") != REDUCER_SCHEMA_VERSION:
        raise ValueError("unsupported reducer manifest schema")

    allowed_statuses = {
        "planned",
        "paused",
        "stopped-on-error",
        "groups-complete",
    }

    if manifest.get("status") not in allowed_statuses:
        raise ValueError(
            f"unsupported reducer status: {manifest.get('status')!r}"
        )

    plan = manifest.get("group_plan")
    groups = manifest.get("groups")

    if not isinstance(plan, list) or not plan:
        raise ValueError("reducer group plan is invalid")

    if not isinstance(groups, list):
        raise ValueError("reducer groups field is invalid")

    total_groups = int(manifest.get("total_groups") or 0)
    completed_groups = int(
        manifest.get("completed_groups") or 0
    )

    if total_groups != len(plan):
        raise ValueError("reducer total group count differs from plan")

    if completed_groups != len(groups):
        raise ValueError(
            "completed group count differs from stored groups"
        )

    if completed_groups < 0 or completed_groups > total_groups:
        raise ValueError("completed group count is out of range")

    for position, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            raise ValueError(
                f"stored reducer group {position} is invalid"
            )

        metadata = group.get("group")

        if not isinstance(metadata, dict):
            raise ValueError(
                f"stored reducer group {position} metadata is invalid"
            )

        if int(metadata.get("group_number") or 0) != position:
            raise ValueError(
                "stored reducer groups are not contiguous"
            )

    expected_next = (
        completed_groups + 1
        if completed_groups < total_groups
        else None
    )

    if manifest.get("next_group") != expected_next:
        raise ValueError(
            "reducer next_group does not match progress"
        )


def load_bound_batch(
    reducer: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    binding = reducer.get("batch_manifest")

    if not isinstance(binding, dict):
        raise ValueError("reducer batch binding is invalid")

    batch_path = Path(
        str(binding.get("file") or "")
    ).expanduser().resolve()

    if not batch_path.is_file():
        raise ValueError("bound batch manifest does not exist")

    expected_hash = str(binding.get("sha256") or "").strip()
    current_hash = sha256_file(batch_path)

    if current_hash != expected_hash:
        raise ValueError("bound batch manifest hash changed")

    batch = load_json(batch_path)

    if batch.get("schema_version") != BATCH_SCHEMA_VERSION:
        raise ValueError("bound batch schema changed")

    validate_batch_manifest(batch)

    source = reducer.get("source")

    if not isinstance(source, dict):
        raise ValueError("reducer source binding is invalid")

    source_path = Path(
        str(source.get("file") or "")
    ).expanduser().resolve()

    if not source_path.is_file():
        raise ValueError("bound source file does not exist")

    expected_source_hash = str(source.get("sha256") or "").strip()

    if sha256_file(source_path) != expected_source_hash:
        raise ValueError("bound source file hash changed")

    return batch_path, batch


def build_group_payload(
    batch: dict[str, Any],
    plan_entry: dict[str, Any],
) -> list[dict[str, Any]]:
    source_blocks = plan_entry.get("source_blocks")

    if not isinstance(source_blocks, list) or not source_blocks:
        raise ValueError("group source block list is invalid")

    stored_blocks = batch.get("blocks")

    if not isinstance(stored_blocks, list):
        raise ValueError("batch block list is invalid")

    payload: list[dict[str, Any]] = []

    for raw_number in source_blocks:
        number = int(raw_number)

        if number <= 0 or number > len(stored_blocks):
            raise ValueError(
                f"group references invalid source block {number}"
            )

        entry = stored_blocks[number - 1]
        result = entry.get("result")

        if not isinstance(result, dict):
            raise ValueError(
                f"source block {number} result is invalid"
            )

        # Verworfene Entitäten werden nicht erneut dem LLM angeboten.
        clean_result = {
            key: value
            for key, value in result.items()
            if key != "entity_rejections"
        }

        payload.append(
            {
                "source_block": number,
                "result": clean_result,
            }
        )

    return payload


def build_group_prompt(
    *,
    source_name: str,
    group_number: int,
    source_blocks: list[int],
    payload: list[dict[str, Any]],
) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return f"""
Du reduzierst bereits geprüfte, lokale MEMORIA-Archivblöcke zu genau
einem lesbaren Archivabschnitt.

Quelle: {source_name}
Reducer-Gruppe: {group_number}
Quellblöcke: {source_blocks}

REGELN:
- Nutze ausschließlich die gelieferten Blockresultate.
- Erfinde keine Personen, Rollen, Ereignisse oder Entscheidungen.
- Bewahre zeitliche Entwicklung, wichtige Erinnerungen und Unsicherheiten.
- Wiederholungen dürfen zusammengeführt werden.
- Verworfene Entitäten sind nicht Teil der Eingabe und dürfen nicht
  rekonstruiert werden.
- Antworte ausschließlich mit genau einem JSON-Objekt.
- Keine Einleitung und kein Markdown.

PFLICHTSCHEMA:
{{
  "title": "nichtleerer Abschnittstitel",
  "summary": "lesbare, zusammenhängende Abschnittszusammenfassung",
  "themes": ["..."],
  "important_memories": ["..."],
  "people_and_entities": [
    {{
      "name": "...",
      "description": "...",
      "source_blocks": [1, 2]
    }}
  ],
  "projects_and_decisions": ["..."],
  "uncertainties": ["..."],
  "evidence": ["..."]
}}

Die Werte in source_blocks dürfen nur aus {source_blocks} stammen.

BLOCKRESULTATE:
{serialized}
""".strip()


def normalize_string_list(
    value: Any,
    *,
    field: str,
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"group result {field} is not a list")

    normalized: list[str] = []

    for item in value:
        if not isinstance(item, str):
            raise ValueError(
                f"group result {field} contains a non-string"
            )

        clean = " ".join(item.split())

        if clean:
            normalized.append(clean)

    return normalized


def normalize_group_entities(
    value: Any,
    *,
    source_text: str,
    allowed_blocks: set[int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(value, list):
        raise ValueError(
            "group result people_and_entities is not a list"
        )

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    source_match = normalized_match_text(source_text)

    for item in value:
        if not isinstance(item, dict):
            raise ValueError(
                "group entity entries must be JSON objects"
            )

        name = " ".join(str(item.get("name") or "").split())
        description = " ".join(
            str(item.get("description") or "").split()
        )
        raw_blocks = item.get("source_blocks")

        if not name:
            raise ValueError("group entity has no valid name")

        if not description:
            raise ValueError(
                f"group entity has no description: {name}"
            )

        if not isinstance(raw_blocks, list) or not raw_blocks:
            raise ValueError(
                f"group entity has invalid source_blocks: {name}"
            )

        entity_blocks: list[int] = []

        for raw_block in raw_blocks:
            if isinstance(raw_block, bool):
                raise ValueError(
                    f"group entity has invalid block reference: {name}"
                )

            block_number = int(raw_block)

            if block_number not in allowed_blocks:
                raise ValueError(
                    f"group entity references foreign block: {name}"
                )

            if block_number not in entity_blocks:
                entity_blocks.append(block_number)

        if normalized_match_text(name) not in source_match:
            rejected.append(
                {
                    "name": name,
                    "reason": "name-not-present-in-group-input",
                }
            )
            continue

        accepted.append(
            {
                "name": name,
                "description": description,
                "source_blocks": sorted(entity_blocks),
            }
        )

    return accepted, rejected


def normalize_group_result(
    value: Any,
    *,
    source_text: str,
    source_blocks: list[int],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("group result is not a JSON object")

    title = " ".join(str(value.get("title") or "").split())
    summary = " ".join(str(value.get("summary") or "").split())

    if not title:
        raise ValueError("group result has no valid title")

    if not summary:
        raise ValueError("group result has no valid summary")

    result: dict[str, Any] = {
        "title": title,
        "summary": summary,
    }

    for field in STRING_LIST_FIELDS:
        result[field] = normalize_string_list(
            value.get(field),
            field=field,
        )

    entities, rejections = normalize_group_entities(
        value.get("people_and_entities"),
        source_text=source_text,
        allowed_blocks=set(source_blocks),
    )

    result["people_and_entities"] = entities
    result["entity_rejections"] = rejections
    return result


def build_group_schema_retry_prompt(prompt: str) -> str:
    return (
        prompt
        + """

SCHEMA-KORREKTUR – ZWEITER UND LETZTER VERSUCH:
- Beginne unmittelbar mit {
- Gib genau ein JSON-Objekt aus.
- title und summary müssen nichtleere Strings sein.
- Alle verlangten Listenfelder müssen vorhanden sein.
- people_and_entities muss Objekte mit name, description und
  source_blocks enthalten.
- source_blocks darf nur Nummern aus der angegebenen Gruppe enthalten.
- Keine Einleitung, keine Analyse und kein Markdown.
""".rstrip()
    )


def summarize_group(
    *,
    adapter: Any,
    prompt: str,
    source_text: str,
    source_blocks: list[int],
) -> tuple[dict[str, Any], bool, bool]:
    response, reasoning_retry_used = send_with_final_json_retry(
        adapter,
        prompt,
    )
    schema_retry_used = False

    try:
        result = normalize_group_result(
            extract_json_object(response),
            source_text=source_text,
            source_blocks=source_blocks,
        )
    except ValueError:
        # Insgesamt maximal zwei Backend-Aufrufe.
        if reasoning_retry_used:
            raise

        schema_retry_used = True
        response = adapter.send(
            build_group_schema_retry_prompt(prompt)
        )
        result = normalize_group_result(
            extract_json_object(response),
            source_text=source_text,
            source_blocks=source_blocks,
        )

    return result, reasoning_retry_used, schema_retry_used


def preflight_prompt(
    *,
    prompt: str,
    runtime: dict[str, Any],
    headroom_tokens: int = DEFAULT_CONTEXT_HEADROOM,
    chars_per_token: float = DEFAULT_CHARS_PER_TOKEN,
) -> dict[str, Any]:
    if chars_per_token <= 0:
        raise ValueError("chars_per_token must be greater than zero")

    context_length = int(runtime.get("context_length") or 0)
    max_tokens = int(runtime.get("max_tokens") or 0)

    if context_length <= 0 or max_tokens <= 0:
        raise ValueError("runtime token limits are invalid")

    estimated_prompt_tokens = int(
        math.ceil(len(prompt) / chars_per_token)
    )

    estimated_total = (
        estimated_prompt_tokens
        + max_tokens
        + int(headroom_tokens)
    )

    allowed = estimated_total <= context_length

    result = {
        "prompt_chars": len(prompt),
        "estimated_prompt_tokens": estimated_prompt_tokens,
        "max_output_tokens": max_tokens,
        "context_headroom_tokens": int(headroom_tokens),
        "estimated_total_tokens": estimated_total,
        "context_length": context_length,
        "allowed": allowed,
    }

    if not allowed:
        raise ValueError(
            "group prompt exceeds safe context allowance: "
            f"estimated_total={estimated_total}, "
            f"context_length={context_length}"
        )

    return result


def run_next_group(
    *,
    reducer_manifest_path: Path,
    adapter: Any,
    runtime_label: dict[str, Any],
    resume: bool,
) -> dict[str, Any]:
    if not resume:
        raise ValueError(
            "existing reducer plan requires explicit --resume"
        )

    reducer_manifest_path = (
        reducer_manifest_path.expanduser().resolve()
    )

    if not reducer_manifest_path.is_file():
        raise ValueError("reducer manifest does not exist")

    reducer = load_json(reducer_manifest_path)
    validate_reducer_manifest(reducer)

    if reducer["status"] == "groups-complete":
        return reducer

    if reducer.get("runtime") != runtime_signature(runtime_label):
        raise ValueError("runtime configuration differs from reducer plan")

    batch_path, batch = load_bound_batch(reducer)
    batch_hash_before = sha256_file(batch_path)

    source_path = Path(
        str(reducer["source"]["file"])
    ).expanduser().resolve()
    source_hash_before = sha256_file(source_path)

    group_number = int(reducer["next_group"])
    plan_entry = reducer["group_plan"][group_number - 1]
    source_blocks = [
        int(number)
        for number in plan_entry["source_blocks"]
    ]

    payload = build_group_payload(batch, plan_entry)
    source_text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    prompt = build_group_prompt(
        source_name=str(reducer["source"].get("name") or ""),
        group_number=group_number,
        source_blocks=source_blocks,
        payload=payload,
    )

    preflight = preflight_prompt(
        prompt=prompt,
        runtime=runtime_label,
    )

    try:
        (
            result,
            reasoning_retry_used,
            schema_retry_used,
        ) = summarize_group(
            adapter=adapter,
            prompt=prompt,
            source_text=source_text,
            source_blocks=source_blocks,
        )
    except Exception as exc:
        reducer["status"] = "stopped-on-error"
        reducer["next_group"] = group_number
        reducer["last_error"] = {
            "at": utc_now(),
            "group_number": group_number,
            "message": str(exc),
        }
        reducer["updated_at"] = utc_now()
        reducer["last_invocation"] = {
            "processed_groups": 0,
            "group_number": group_number,
        }

        write_json_atomic(
            reducer_manifest_path,
            reducer,
        )
        raise

    if sha256_file(batch_path) != batch_hash_before:
        raise RuntimeError(
            "batch manifest changed during group reduction"
        )

    if sha256_file(source_path) != source_hash_before:
        raise RuntimeError(
            "source file changed during group reduction"
        )

    group_result = {
        "schema_version": GROUP_SCHEMA_VERSION,
        "mode": "read-only-local-llm",
        "group": {
            "group_number": group_number,
            "source_block_start": source_blocks[0],
            "source_block_end": source_blocks[-1],
            "source_blocks": source_blocks,
        },
        "preflight": preflight,
        "runtime": {
            "adapter": runtime_label.get("adapter"),
            "base_url": runtime_label.get("base_url"),
            "model": runtime_label.get("model"),
            "max_tokens": runtime_label.get("max_tokens"),
            "reasoning_retry_used": reasoning_retry_used,
            "schema_retry_used": schema_retry_used,
        },
        "result": result,
        "policy": {
            "batch_manifest_modified": False,
            "source_modified": False,
            "candidate_written": False,
            "durable_memory_written": False,
            "automatic_promotion": False,
            "archive_result_written": False,
        },
    }

    reducer["groups"].append(group_result)
    reducer["completed_groups"] = group_number
    reducer["group_plan"][group_number - 1]["status"] = "complete"

    if group_number >= int(reducer["total_groups"]):
        reducer["status"] = "groups-complete"
        reducer["next_group"] = None
    else:
        reducer["status"] = "paused"
        reducer["next_group"] = group_number + 1

    reducer["last_error"] = None
    reducer["updated_at"] = utc_now()
    reducer["last_invocation"] = {
        "processed_groups": 1,
        "group_number": group_number,
    }

    write_json_atomic(
        reducer_manifest_path,
        reducer,
    )

    return reducer


def print_human(
    manifest: dict[str, Any],
    manifest_path: Path,
) -> None:
    print("## MEMORIA BIG ARCHIVE GROUP RUNNER V0.1")
    print("Mode: LOCAL / CHECKPOINTED / NO MEMORY WRITE")
    print(f"Manifest: {manifest_path.expanduser().resolve()}")
    print(f"Status: {manifest['status']}")
    print(
        "Progress: "
        f"{manifest['completed_groups']}/"
        f"{manifest['total_groups']}"
    )
    print(f"Next group: {manifest.get('next_group')}")
    print(
        "Processed this invocation: "
        f"{manifest.get('last_invocation', {}).get('processed_groups', 0)}"
    )

    print("\nPolicy:")
    print("- Source modified: False")
    print("- Batch manifest modified: False")
    print("- Candidate written: False")
    print("- Durable memory written: False")
    print("- Automatic promotion: False")
    print("- Reducer checkpoint written: True")

    if manifest["status"] == "groups-complete":
        print("OK all reducer groups summarized.")
    else:
        print("OK reducer group checkpoint saved; resume required.")


def command_run(args: argparse.Namespace) -> int:
    try:
        config = apply_output_budget(
            ConfigureManager().load_runtime_config(),
            args.max_output_tokens,
        )
        require_local_runtime(config)
        adapter = build_adapter(config)

        manifest = run_next_group(
            reducer_manifest_path=Path(args.manifest),
            adapter=adapter,
            runtime_label=config,
            resume=args.resume,
        )
    except Exception as exc:
        print(f"ABORT: {exc}")
        return 23

    print_human(manifest, Path(args.manifest))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Process exactly one planned Big Archive reducer group. "
            "No Candidate or durable-memory write."
        )
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    run = sub.add_parser("run")
    run.add_argument("--manifest", required=True)
    run.add_argument(
        "--max-output-tokens",
        type=int,
        default=20000,
    )
    run.add_argument("--resume", action="store_true")
    run.set_defaults(func=command_run)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
