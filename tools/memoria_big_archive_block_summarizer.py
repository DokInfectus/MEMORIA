#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / "tools"

for entry in (PROJECT_ROOT, TOOLS_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from adapter.exceptions import AdapterExecutionError
from adapter.factory import build_adapter
from configure.manager import ConfigureManager
from memoria_big_archive_section_analyzer import build_sections
from memoria_memory_file_import import (
    chunk_text,
    load_settings,
    read_import_file,
    sha256_file,
)


SCHEMA_VERSION = "big-archive-block-summary-v0.1"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

RESULT_LIST_FIELDS = (
    "themes",
    "important_memories",
    "projects_and_decisions",
    "uncertainties",
    "evidence",
)

ENTITY_SUPPORT_VALUES = {
    "mentioned-only",
    "explicit",
}


class AdapterLike(Protocol):
    def send(self, prompt: str) -> str:
        ...


def require_local_runtime(config: dict[str, Any]) -> None:
    """Allow this private archive tool to use local backends only."""
    adapter_name = str(config.get("adapter") or "").strip()

    if adapter_name == "MockAdapter":
        return

    base_url = str(config.get("base_url") or "").strip()
    parsed = urlparse(base_url)

    if parsed.hostname not in LOCAL_HOSTS:
        raise ValueError(
            "configured backend is not local; "
            "Big Archive summarization only permits localhost/127.0.0.1/::1"
        )


def load_block(
    path: Path,
    *,
    block_number: int,
    max_chunk_chars: int,
    section_max_chunks: int,
    section_max_chars: int,
    section_min_chunks: int,
) -> tuple[dict[str, Any], str]:
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

    if block_number < 1 or block_number > len(sections):
        raise ValueError(
            f"block number must be between 1 and {len(sections)}"
        )

    section = sections[block_number - 1]
    start = section.source_chunk_start
    end = section.source_chunk_end
    selected_chunks = chunks[start - 1:end]
    block_text = "\n\n".join(selected_chunks)

    metadata = {
        "block_number": block_number,
        "block_count": len(sections),
        "source_chunk_start": start,
        "source_chunk_end": end,
        "chunk_count": len(selected_chunks),
        "char_count": len(block_text),
        "technical_chunk_count": len(chunks),
    }

    return metadata, block_text


def build_prompt(
    *,
    source_name: str,
    block: dict[str, Any],
    block_text: str,
) -> str:
    schema_example = json.dumps(
        {
            "title": "kurzer aussagekräftiger deutscher Titel",
            "summary": "treue strukturierte Zusammenfassung",
            "themes": ["Thema"],
            "important_memories": [
                "wichtige Erinnerung oder Kontinuität"
            ],
            "people_and_entities": [
                {
                    "name": "Person, KI, Rolle, Projekt oder Ort",
                    "role": None,
                    "support": "mentioned-only",
                    "evidence": "kurzer wörtlicher Beleg mit dem Namen",
                }
            ],
            "projects_and_decisions": [
                "Projekt, Entscheidung oder technischer Stand"
            ],
            "uncertainties": [
                "unklare oder widersprüchliche Angabe"
            ],
            "evidence": [
                "kurzer wörtlicher Beleg aus dem gelieferten Block"
            ],
        },
        indent=2,
        ensure_ascii=False,
    )

    return f"""
Du strukturierst einen Block aus einer ausdrücklich vom Benutzer gewählten
lokalen Gedächtnisdatei.

Quelle: {source_name}
Block: {block["block_number"]} von {block["block_count"]}
Technische Chunks: {block["source_chunk_start"]}-{block["source_chunk_end"]}

Regeln:
- Bleibe vollständig beim gelieferten Text.
- Erfinde keine Ereignisse, Beziehungen, Entscheidungen oder Fakten.
- Emotionale, persönliche und technische Inhalte sind gleichberechtigt.
- Werte den Benutzer oder seine Beziehungen nicht moralisch.
- Entferne keine Inhalte nur deshalb, weil sie ungewöhnlich, privat,
  spielerisch oder emotional sind.
- Verdichte Wiederholungen, ohne ihren Sinn zu verändern.
- Markiere unklare oder widersprüchliche Angaben unter uncertainties.
- Arbeite ausschließlich blocklokal. Nutze kein angenommenes Wissen aus
  früheren oder späteren Archivblöcken.
- Weise Personen oder Entitäten nur dann eine Rolle oder Beziehung zu,
  wenn diese im gelieferten Block ausdrücklich belegt ist.
- Jede Entität muss ein Objekt mit name, role, support und evidence sein.
- support darf nur "mentioned-only" oder "explicit" sein.
- Bei "mentioned-only" muss role null sein.
- Bei "explicit" muss role gesetzt und durch evidence im Block belegt sein.
- evidence muss ein kurzer wörtlicher Beleg aus genau diesem Block sein
  und den Namen der Entität enthalten.
- Gib unter evidence zusätzlich kurze allgemeine Textbelege aus diesem
  Block an.
- Gib keine Gedankenkette, Begründung oder Markdown-Codeblöcke aus.
- Gib ausschließlich ein gültiges JSON-Objekt zurück.

Erforderliches JSON-Schema:
{schema_example}

BLOCKTEXT BEGINN
{block_text}
BLOCKTEXT ENDE
""".strip()

def extract_json_object(response: str) -> dict[str, Any]:
    text = str(response or "").strip()

    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    decoder = json.JSONDecoder()

    for index, char in enumerate(text):
        if char != "{":
            continue

        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue

        if isinstance(value, dict):
            return value

    raise ValueError("adapter response contains no valid JSON object")


def normalized_match_text(value: str) -> str:
    """Create a comparison-only text key.

    Original source text and returned evidence remain unchanged.
    Unicode dash punctuation is treated like whitespace so variants such as
    "Google-Entwickler" and "Google Entwickler" compare equally.
    """
    normalized = unicodedata.normalize(
        "NFKC",
        str(value or ""),
    )

    normalized = "".join(
        " "
        if (
            unicodedata.category(character) == "Pd"
            or character in {"\u00ad", "\u2212"}
        )
        else character
        for character in normalized
    )

    return " ".join(
        normalized.casefold().split()
    )


ROLE_TERM_STOPWORDS = {
    "als",
    "am",
    "an",
    "auf",
    "aus",
    "bei",
    "das",
    "dem",
    "den",
    "der",
    "des",
    "die",
    "ein",
    "eine",
    "einer",
    "für",
    "im",
    "in",
    "mit",
    "oder",
    "rolle",
    "und",
    "vom",
    "von",
    "zum",
    "zur",
}


def meaningful_role_terms(role: str | None) -> list[str]:
    raw_terms = re.findall(
        r"[0-9a-zäöüß]+",
        normalized_match_text(role or ""),
    )

    terms: list[str] = []

    for term in raw_terms:
        if len(term) < 3:
            continue

        if term in ROLE_TERM_STOPWORDS:
            continue

        if term not in terms:
            terms.append(term)

    return terms


def matched_role_terms(
    role: str | None,
    evidence: str,
) -> list[str]:
    evidence_match = normalized_match_text(evidence)

    return [
        term
        for term in meaningful_role_terms(role)
        if term in evidence_match
    ]


def role_supported_by_evidence(
    role: str | None,
    evidence: str,
) -> bool:
    terms = meaningful_role_terms(role)

    if not terms:
        return False

    matched = matched_role_terms(role, evidence)

    if len(terms) <= 2:
        required = len(terms)
    else:
        required = max(2, (len(terms) + 1) // 2)

    return len(matched) >= required


def entity_evidence_candidates(
    block_text: str,
    name: str,
    *,
    max_chars: int = 280,
) -> list[str]:
    name_match = normalized_match_text(name)

    if not name_match:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    def add_candidate(raw_value: str) -> None:
        value = " ".join(str(raw_value or "").split())

        if not value:
            return

        value_match = normalized_match_text(value)

        if name_match not in value_match:
            return

        if len(value) > max_chars:
            position = value_match.find(name_match)
            start = max(0, position - 90)
            end = min(
                len(value),
                position + len(name) + 170,
            )
            value = value[start:end].strip()

        key = normalized_match_text(value)

        if key and key not in seen:
            seen.add(key)
            candidates.append(value)

    # Einzelne Zeilen.
    for raw_line in block_text.splitlines():
        add_candidate(raw_line)

    # Absätze können Rolle und Name über mehrere Zeilen enthalten.
    for raw_paragraph in block_text.split("\n\n"):
        add_candidate(raw_paragraph)

    # Letzter Fallback: Fenster um jede Namensstelle im kompakten Text.
    compact = " ".join(block_text.split())
    compact_match = normalized_match_text(compact)
    search_from = 0

    while True:
        position = compact_match.find(name_match, search_from)

        if position == -1:
            break

        start = max(0, position - 100)
        end = min(
            len(compact),
            position + len(name) + 180,
        )

        add_candidate(compact[start:end])
        search_from = position + max(1, len(name_match))

    return candidates


def find_best_entity_evidence(
    block_text: str,
    name: str,
    role: str | None,
) -> str:
    candidates = entity_evidence_candidates(
        block_text,
        name,
    )

    if not candidates:
        return ""

    role_match = normalized_match_text(role or "")

    def score(candidate: str) -> tuple[int, int, int]:
        candidate_match = normalized_match_text(candidate)

        exact_role = int(
            bool(role_match)
            and role_match in candidate_match
        )

        matched_count = len(
            matched_role_terms(role, candidate)
        )

        # Kürzere Belege gewinnen nur bei gleichem Rollen-Score.
        return (
            exact_role,
            matched_count,
            -len(candidate),
        )

    return max(candidates, key=score)


def normalize_entities(
    items: Any,
    *,
    block_text: str,
    rejections: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise ValueError(
            "summary JSON field must be a list: people_and_entities"
        )

    block_match = normalized_match_text(block_text)
    cleaned: list[dict[str, Any]] = []

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(
                "people_and_entities entries must be JSON objects"
            )

        name = " ".join(str(item.get("name") or "").split())
        support = str(item.get("support") or "").strip()
        evidence = " ".join(str(item.get("evidence") or "").split())
        raw_role = item.get("role")

        if not name:
            raise ValueError(f"entity {index} has no valid name")

        if support not in ENTITY_SUPPORT_VALUES:
            raise ValueError(
                f"entity {name!r} has invalid support: {support!r}"
            )

        if not evidence:
            raise ValueError(f"entity {name!r} has no evidence")

        name_match = normalized_match_text(name)
        evidence_match = normalized_match_text(evidence)

        if name_match not in block_match:
            if rejections is not None:
                rejections.append(
                    {
                        "name": name,
                        "role": (
                            " ".join(
                                str(raw_role or "").split()
                            )
                            or None
                        ),
                        "support": support,
                        "reason": "name-not-present-in-block",
                    }
                )

            # Strict validation remains: the unsupported entity is not
            # accepted. Only the batch-stopping exception is avoided.
            continue

        role = " ".join(str(raw_role or "").split()) or None

        provided_evidence_is_valid = (
            bool(evidence_match)
            and evidence_match in block_match
            and name_match in evidence_match
        )

        best_evidence = find_best_entity_evidence(
            block_text,
            name,
            role,
        )

        if not best_evidence:
            raise ValueError(
                f"no exact source mention found for entity: {name}"
            )

        guard_action = "accepted"

        if support == "explicit":
            if (
                role is not None
                and provided_evidence_is_valid
                and role_supported_by_evidence(role, evidence)
            ):
                pass

            elif (
                role is not None
                and role_supported_by_evidence(
                    role,
                    best_evidence,
                )
            ):
                evidence = best_evidence
                guard_action = "evidence-reselected"

            else:
                support = "mentioned-only"
                role = None
                evidence = best_evidence
                guard_action = "downgraded-to-mentioned-only"

        else:
            role_was_removed = raw_role not in (None, "")
            role = None

            if not provided_evidence_is_valid:
                evidence = best_evidence

                if role_was_removed:
                    guard_action = (
                        "evidence-reselected-and-role-removed"
                    )
                else:
                    guard_action = "evidence-reselected"

            elif role_was_removed:
                guard_action = "role-removed-mentioned-only"

        cleaned.append(
            {
                "name": name,
                "role": role,
                "support": support,
                "evidence": evidence,
                "guard_action": guard_action,
            }
        )

    return cleaned


def normalize_result(
    value: dict[str, Any],
    *,
    block_text: str,
) -> dict[str, Any]:
    title = value.get("title")
    summary = value.get("summary")

    if not isinstance(title, str) or not title.strip():
        raise ValueError("summary JSON has no valid title")

    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("summary JSON has no valid summary")

    result: dict[str, Any] = {
        "title": " ".join(title.split()),
        "summary": summary.strip(),
    }

    for field in RESULT_LIST_FIELDS:
        items = value.get(field)

        if not isinstance(items, list):
            raise ValueError(f"summary JSON field must be a list: {field}")

        cleaned: list[str] = []

        for item in items:
            if not isinstance(item, str):
                raise ValueError(
                    f"summary JSON list contains non-text item: {field}"
                )

            item_text = " ".join(item.split())
            if item_text:
                cleaned.append(item_text)

        result[field] = cleaned

    entity_rejections: list[dict[str, Any]] = []

    result["people_and_entities"] = normalize_entities(
        value.get("people_and_entities"),
        block_text=block_text,
        rejections=entity_rejections,
    )
    result["entity_rejections"] = entity_rejections

    return result



def send_with_final_json_retry(
    adapter: AdapterLike,
    prompt: str,
) -> tuple[str, bool]:
    """Request one normal final JSON response.

    The global adapter remains strict and never exposes reasoning_content.
    A second request is only attempted for the known reasoning-only error.
    """
    try:
        return adapter.send(prompt), False
    except AdapterExecutionError as exc:
        message = str(exc)

        reasoning_only = (
            "reasoning_content" in message
            and "no normal assistant content" in message
        )

        if not reasoning_only:
            raise

    retry_prompt = (
        prompt
        + """

ZWEITER UND LETZTER AUSGABEVERSUCH:
- Beginne deine Antwort unmittelbar mit {
- Gib ausschließlich das verlangte JSON-Objekt aus.
- Keine Analyse, keine Einleitung und kein Markdown.
- Gib eine normale finale Assistant-Antwort aus.
- Nutze kein reasoning_content als Endausgabe.
""".rstrip()
    )

    return adapter.send(retry_prompt), True



def parse_summary_response(
    response: str,
    *,
    block_text: str,
) -> dict[str, Any]:
    return normalize_result(
        extract_json_object(response),
        block_text=block_text,
    )


def build_schema_retry_prompt(prompt: str) -> str:
    return (
        prompt
        + """

SCHEMA-KORREKTUR – ZWEITER UND LETZTER VERSUCH:
Die vorherige Antwort erfüllte das verlangte JSON-Schema nicht vollständig.

Pflicht:
- Beginne unmittelbar mit {
- Gib genau ein JSON-Objekt aus.
- title und summary müssen nichtleere Strings sein.
- themes, important_memories, people_and_entities,
  projects_and_decisions, uncertainties und evidence müssen vorhanden sein.
- Alle Listenfelder müssen JSON-Listen sein.
- people_and_entities muss Objekte mit name, role, support und evidence enthalten.
- Keine Einleitung, keine Erklärung und kein Markdown.
""".rstrip()
    )


def summarize_block(
    *,
    source_path: Path,
    block_number: int,
    adapter: AdapterLike,
    runtime_label: dict[str, Any],
    max_chunk_chars: int = 1800,
    section_max_chunks: int = 40,
    section_max_chars: int = 60000,
    section_min_chunks: int = 5,
) -> dict[str, Any]:
    source_path = source_path.expanduser().resolve()
    before_sha256 = sha256_file(source_path)

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

    response, reasoning_retry_used = send_with_final_json_retry(
        adapter,
        prompt,
    )

    schema_retry_used = False

    try:
        result = parse_summary_response(
            response,
            block_text=block_text,
        )
    except ValueError:
        # Maximal zwei Backend-Aufrufe insgesamt:
        # Nach einem bereits verwendeten reasoning-only Retry wird kein
        # zusätzlicher dritter Versuch gestartet.
        if reasoning_retry_used:
            raise

        schema_retry_used = True
        response = adapter.send(
            build_schema_retry_prompt(prompt)
        )
        result = parse_summary_response(
            response,
            block_text=block_text,
        )

    for entity in result["people_and_entities"]:
        entity["source_block"] = block["block_number"]
        entity["source_chunk_start"] = block["source_chunk_start"]
        entity["source_chunk_end"] = block["source_chunk_end"]

    after_sha256 = sha256_file(source_path)

    if before_sha256 != after_sha256:
        raise RuntimeError("source file changed during summarization")

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "read-only-local-llm",
        "source": {
            "file": str(source_path),
            "name": source_path.name,
            "sha256": before_sha256,
        },
        "block": block,
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
            "explicit_file_only": True,
            "local_backend_only": True,
            "private_directory_scan": False,
            "source_modified": False,
            "candidate_written": False,
            "durable_memory_written": False,
            "result_file_written": False,
        },
    }


def print_human(manifest: dict[str, Any]) -> None:
    block = manifest["block"]
    result = manifest["result"]
    policy = manifest["policy"]
    runtime = manifest["runtime"]

    print("## MEMORIA BIG ARCHIVE BLOCK SUMMARIZER V0.1")
    print("Mode: READ-ONLY / LOCAL BACKEND ONLY")
    print(f"Source: {manifest['source']['file']}")
    print(
        f"Block: {block['block_number']}/{block['block_count']} "
        f"| chunks={block['source_chunk_start']}-"
        f"{block['source_chunk_end']} "
        f"| chars={block['char_count']}"
    )
    print(f"Adapter: {runtime.get('adapter')}")
    print(f"Base URL: {runtime.get('base_url')}")
    print(f"Model: {runtime.get('model')}")
    print(f"Max output tokens: {runtime.get('max_tokens')}")
    print(
        "Reasoning-only retry used: "
        f"{runtime.get('reasoning_retry_used', False)}"
    )
    print(
        "Schema retry used: "
        f"{runtime.get('schema_retry_used', False)}"
    )
    print()
    print("## Structured Result")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print()
    print("Policy:")
    print(f"- Source modified: {policy['source_modified']}")
    print(f"- Candidate written: {policy['candidate_written']}")
    print(f"- Durable memory written: {policy['durable_memory_written']}")
    print(f"- Result file written: {policy['result_file_written']}")
    print("OK one archive block summarized.")



MIN_SUMMARIZER_OUTPUT_TOKENS = 1024
SUMMARIZER_CONTEXT_HEADROOM_TOKENS = 4096


def apply_output_budget(
    config: dict[str, Any],
    requested_tokens: int | None,
) -> dict[str, Any]:
    """Return a runtime-config copy with a summarizer-local output budget.

    The persisted runtime.json is never modified.
    """
    updated = dict(config)

    if requested_tokens is None:
        return updated

    requested = int(requested_tokens)

    if requested < MIN_SUMMARIZER_OUTPUT_TOKENS:
        raise ValueError(
            "max output tokens must be at least "
            f"{MIN_SUMMARIZER_OUTPUT_TOKENS}"
        )

    context_length = int(updated.get("context_length") or 0)

    if context_length > 0:
        maximum = (
            context_length
            - SUMMARIZER_CONTEXT_HEADROOM_TOKENS
        )

        if requested > maximum:
            raise ValueError(
                "max output tokens exceed safe context allowance: "
                f"requested={requested}, maximum={maximum}, "
                f"context_length={context_length}"
            )

    updated["max_tokens"] = requested
    return updated


def command_summarize(args: argparse.Namespace) -> int:
    values = (
        args.block,
        args.max_chunk_chars,
        args.section_max_chunks,
        args.section_max_chars,
        args.section_min_chunks,
    )

    if any(value <= 0 for value in values):
        print("ABORT: block and analyzer limits must be greater than zero.")
        return 23

    try:
        config = apply_output_budget(
            ConfigureManager().load_runtime_config(),
            args.max_output_tokens,
        )
        require_local_runtime(config)
        adapter = build_adapter(config)

        manifest = summarize_block(
            source_path=Path(args.file),
            block_number=args.block,
            adapter=adapter,
            runtime_label=config,
            max_chunk_chars=args.max_chunk_chars,
            section_max_chunks=args.section_max_chunks,
            section_max_chars=args.section_max_chars,
            section_min_chunks=args.section_min_chunks,
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
        print_human(manifest)

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize exactly one big-archive block locally."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    summarize = sub.add_parser("summarize")
    summarize.add_argument("--file", required=True)
    summarize.add_argument("--block", required=True, type=int)
    summarize.add_argument("--max-chunk-chars", type=int, default=1800)
    summarize.add_argument("--section-max-chunks", type=int, default=40)
    summarize.add_argument("--section-max-chars", type=int, default=60000)
    summarize.add_argument("--section-min-chunks", type=int, default=5)
    summarize.add_argument(
        "--max-output-tokens",
        type=int,
        default=None,
        help="Summarizer-local output budget; runtime.json remains unchanged",
    )
    summarize.add_argument("--json", action="store_true")
    summarize.set_defaults(func=command_summarize)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
