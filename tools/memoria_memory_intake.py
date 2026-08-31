#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

from memoria_storage_paths import managed_path as _memoria_managed_path

RULE_DIR = Path(os.environ.get("MEMORIA_RULE_DIR", str(ROOT / "config" / "rules")))
MEMORY_DIR = _memoria_managed_path(
    "memory",
    env_var="MEMORIA_MEMORY_DIR",
    fallback_rel="knowledge/memory",
)
CANDIDATE_DIR = _memoria_managed_path(
    "memory_candidates",
    env_var="MEMORIA_CANDIDATE_DIR",
    fallback_rel="knowledge/memory_candidates",
)

SENSITIVE_PATTERNS = (
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "possible API key"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE), "possible bearer token"),
    (re.compile(r"\b(api[_ -]?key|password|passwd|secret|token)\b\s*[:=]", re.IGNORECASE), "secret-like assignment"),
)

SMALLTALK_PATTERNS = (
    re.compile(r"^(ok|okay|jo|ja|nein|danke|thanks|lol|haha|hehe|passt|alles gut)[.!?\s]*$", re.IGNORECASE),
    re.compile(r"^(guten morgen|guten abend|gute nacht|hallo|hi|hey)[.!?\s]*$", re.IGNORECASE),
)


def collapse_repeated_words(line: str) -> tuple[str, int]:
    out: list[str] = []
    previous = None
    removed = 0

    for word in line.split():
        key = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß_-]+", "", word).lower()
        if key and key == previous:
            removed += 1
            continue
        out.append(word)
        previous = key

    return " ".join(out), removed


def normalize_text(text: str) -> tuple[str, dict[str, int]]:
    stats = {
        "empty_lines_removed": 0,
        "duplicate_lines_removed": 0,
        "repeated_words_removed": 0,
    }

    lines: list[str] = []
    seen: set[str] = set()

    for raw in text.replace("\r\n", "\n").splitlines():
        clean = " ".join(raw.strip().split())
        if not clean:
            stats["empty_lines_removed"] += 1
            continue

        clean, removed_words = collapse_repeated_words(clean)
        stats["repeated_words_removed"] += removed_words

        key = clean.lower()
        if key in seen:
            stats["duplicate_lines_removed"] += 1
            continue

        seen.add(key)
        lines.append(clean)

    return "\n".join(lines).strip(), stats


def scan_sensitive(text: str) -> list[str]:
    warnings: list[str] = []
    for pattern, label in SENSITIVE_PATTERNS:
        if pattern.search(text):
            warnings.append(label)
    return warnings



def read_json_file(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_enabled_filter_preset_rules() -> list[dict[str, Any]]:
    """Load user-enabled standard filter presets as intake rules.

    Presets only create review candidates. They never write durable memory.
    Custom important terms are intentionally separate and handled by
    load_custom_important_terms().
    """
    presets_path = RULE_DIR / "system" / "filter_presets.json"
    enabled_path = RULE_DIR / "user" / "enabled_filter_presets.json"

    presets_data = read_json_file(presets_path, {"presets": []})
    enabled_data = read_json_file(enabled_path, {"enabled_presets": []})

    enabled = {
        str(item).strip()
        for item in enabled_data.get("enabled_presets", [])
        if str(item).strip()
    }

    if not enabled:
        return []

    project_like = {
        "project",
        "programming",
        "development",
        "server_admin",
        "hardware",
        "ai_llm",
        "memory",
        "documents",
        "spreadsheets",
        "work",
        "calculation",
        "inventory",
        "finance",
        "research",
        "media_assets",
        "maintenance",
    }

    rules: list[dict[str, Any]] = []

    for item in presets_data.get("presets", []):
        if not isinstance(item, dict):
            continue

        preset_id = str(item.get("id") or "").strip()
        if not preset_id or preset_id not in enabled:
            continue

        if preset_id == "custom_important":
            # Custom filters are managed separately through custom add/del/list.
            continue

        terms = [str(term).strip() for term in item.get("terms", []) if str(term).strip()]
        if not terms:
            continue

        layer = "project" if preset_id in project_like else "user"

        rules.append({
            "id": f"RUL-PRESET-{preset_id.upper().replace('-', '_')}",
            "name": f"Enabled Filter Preset: {item.get('label', preset_id)}",
            "enabled": True,
            "priority": 30,
            "match": terms,
            "action": "create-candidate",
            "category": f"preset:{preset_id}",
            "metadata": {
                "layer": layer,
                "source": "enabled_filter_presets",
                "preset_id": preset_id,
            },
            "_path": str(presets_path),
        })

    return rules


def load_custom_important_terms() -> list[str]:
    terms_path = RULE_DIR / "user" / "custom_important.txt"
    if not terms_path.exists():
        return []

    terms: list[str] = []
    for raw in terms_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line not in terms:
            terms.append(line)

    return terms[:100]


def load_rules() -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []

    if RULE_DIR.exists():
        for path in sorted(RULE_DIR.rglob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue

            if data.get("enabled", True) is False:
                continue

            data["_path"] = str(path)
            rules.append(data)

    rules.extend(load_enabled_filter_preset_rules())

    custom_terms = load_custom_important_terms()
    if custom_terms:
        rules.append({
            "id": "RUL-USER-CUSTOM-IMPORTANT",
            "name": "User Custom Important Terms",
            "enabled": True,
            "priority": 20,
            "match": custom_terms,
            "action": "create-candidate",
            "category": "custom-important",
            "metadata": {
                "layer": "user",
                "source": "config/rules/user/custom_important.txt",
            },
            "_path": str(RULE_DIR / "user" / "custom_important.txt"),
        })

    return sorted(rules, key=lambda item: int(item.get("priority", 100)))

def match_rule(text: str) -> dict[str, Any] | None:
    lowered = text.lower()

    for rule in load_rules():
        terms = rule.get("match", [])
        for term in terms:
            if str(term).lower() in lowered:
                return rule

    return None


def is_smalltalk(text: str) -> bool:
    compact = " ".join(text.split()).strip()
    if len(compact) <= 3:
        return True

    for pattern in SMALLTALK_PATTERNS:
        if pattern.match(compact):
            return True

    return False


def decide(cleaned: str, warnings: list[str]) -> dict[str, Any]:
    lowered = cleaned.lower()

    if warnings:
        return {
            "action": "never-store",
            "category": "sensitive",
            "layer": "none",
            "reason": "sensitive content pattern detected",
            "rule_id": None,
        }

    if not cleaned or is_smalltalk(cleaned):
        return {
            "action": "ignore",
            "category": "smalltalk",
            "layer": "session",
            "reason": "text is empty, trivial or smalltalk",
            "rule_id": None,
        }

    rule = match_rule(cleaned)
    if rule:
        category = str(rule.get("category") or "knowledge")
        raw_action = str(rule.get("action") or "create-candidate").strip().lower()

        metadata = rule.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        explicit_layer = str(metadata.get("layer") or rule.get("layer") or "").strip().lower()
        if explicit_layer in {"core", "user", "project", "session", "none"}:
            layer = explicit_layer
        else:
            layer = "project" if category in {"hardware", "project", "knowledge"} else "user"

        if raw_action in {"ignore", "ignored", "archive"}:
            action = "ignore"
        elif raw_action in {"never-store", "never_store", "block", "blocked"}:
            action = "never-store"
        else:
            action = "create-candidate"

        return {
            "action": action,
            "category": category,
            "layer": layer,
            "reason": f"matched configured rule: {rule.get('name')} ({raw_action})",
            "rule_id": rule.get("id"),
        }

    generic_low_signal = {"test", "testing", "probe", "asdf", "foo", "bar"}
    compact_lowered = " ".join(lowered.split()).strip(" .!?")

    if compact_lowered in generic_low_signal:
        return {
            "action": "ignore",
            "category": "low-signal",
            "layer": "session",
            "reason": "generic test input",
            "rule_id": None,
        }

    if any(term in lowered for term in ("adr", "projekt", "project", "checkpoint", "roadmap", "bug", "nächster schritt")):
        return {
            "action": "create-candidate",
            "category": "project",
            "layer": "project",
            "reason": "project-related wording detected",
            "rule_id": None,
        }

    if any(term in lowered for term in ("persona", "rolle", "stil", "ansprechen", "ton", "beziehung")):
        return {
            "action": "create-candidate",
            "category": "persona",
            "layer": "user",
            "reason": "persona or interaction-style wording detected",
            "rule_id": None,
        }

    if any(term in lowered for term in ("ich möchte", "mir ist wichtig", "ab jetzt", "from now on", "bitte merke", "präferenz")):
        return {
            "action": "create-candidate",
            "category": "preference",
            "layer": "user",
            "reason": "user preference wording detected",
            "rule_id": None,
        }

    return {
        "action": "ignore",
        "category": "low-signal",
        "layer": "session",
        "reason": "no configured memory rule matched",
        "rule_id": None,
    }


def fingerprint(text: str) -> str:
    return re.sub(r"[^a-z0-9äöüß]+", " ", text.lower()).strip()


def token_set(text: str) -> set[str]:
    return {item for item in fingerprint(text).split() if len(item) > 2}


def similarity(a: str, b: str) -> float:
    left = token_set(a)
    right = token_set(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def iter_existing_items() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []

    for base, kind, glob in [
        (MEMORY_DIR, "memory", "MEM-*.json"),
        (CANDIDATE_DIR, "candidate", "CAND-*.json"),
    ]:
        if not base.exists():
            continue

        for path in sorted(base.glob(glob)):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue

            text = "\n".join([
                str(data.get("title", "")),
                str(data.get("content", "")),
                str(data.get("text", "")),
            ]).strip()

            items.append({
                "kind": kind,
                "id": str(data.get("id") or path.stem),
                "title": str(data.get("title", "")),
                "text": text,
            })

    return items


def find_duplicate(cleaned: str) -> dict[str, Any]:
    fp = fingerprint(cleaned)

    for item in iter_existing_items():
        existing = item["text"]
        efp = fingerprint(existing)

        if fp and fp == efp:
            return {"duplicate": True, "match_type": "exact", **item}

        if len(fp) > 40 and (fp in efp or efp in fp):
            return {"duplicate": True, "match_type": "contained", **item}

        score = similarity(cleaned, existing)
        if score >= 0.82:
            return {"duplicate": True, "match_type": f"similar:{score:.2f}", **item}

    return {"duplicate": False}


def make_title(cleaned: str) -> str:
    first = " ".join(cleaned.split())
    return first[:80] if first else "Untitled memory candidate"


def analyze_text(text: str, user_declared_memory: bool = False) -> dict[str, Any]:
    cleaned, stats = normalize_text(text)
    warnings = scan_sensitive(cleaned)

    if user_declared_memory and cleaned and not warnings:
        decision = {
            "action": "create-candidate",
            "category": "user-declared-memory",
            "layer": "user",
            "reason": "user explicitly declared this input as memory material",
            "rule_id": "USER-DECLARED-MEMORY",
        }
    else:
        decision = decide(cleaned, warnings)
    duplicate = find_duplicate(cleaned)

    if duplicate.get("duplicate") and decision["action"] == "create-candidate":
        decision = {
            **decision,
            "action": "ignore",
            "reason": f"duplicate detected: {duplicate.get('id')}",
        }

    result = {
        "version": "memory-intake-v0.3-user-custom-rules",
        "policy": {
            "private_chat_logs_scanned": False,
            "durable_memory_written": False,
            "candidate_written": False,
        },
        "cleaned_text": cleaned,
        "title": make_title(cleaned),
        "filter_stats": stats,
        "safety_warnings": warnings,
        "duplicate": duplicate,
        "decision": decision,
        "suggested_tags": [
            decision["category"],
            f"layer:{decision['layer']}",
            "intake-dry-run",
        ],
    }


    result["candidate_metadata"] = (
        build_intake_candidate_metadata(
            result,
            user_declared_memory=user_declared_memory,
        )
    )

    return result



def parse_metadata_json(raw: str | None) -> dict[str, Any]:
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


def build_intake_candidate_metadata(
    result: dict[str, Any],
    *,
    user_declared_memory: bool,
) -> dict[str, Any]:
    decision = result.get("decision") or {}

    return {
        "memoria_intake": {
            "version": str(
                result.get("version") or ""
            ),
            "context_mode": "full-message",
            "decision_action": str(
                decision.get("action") or ""
            ),
            "category": str(
                decision.get("category") or ""
            ),
            "layer": str(
                decision.get("layer") or ""
            ),
            "rule_id": decision.get("rule_id"),
            "reason": str(
                decision.get("reason") or ""
            ),
            "user_declared_memory": bool(
                user_declared_memory
            ),
        }
    }


def merge_candidate_metadata(
    internal: dict[str, Any],
    external: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(external)

    # Der interne Audit-Block darf nicht von außen
    # überschrieben oder als Berechtigung ausgegeben werden.
    merged.update(internal)

    return merged


def create_candidate_from_result(result: dict[str, Any]) -> dict[str, Any]:
    decision = result.get("decision", {})

    if decision.get("action") != "create-candidate":
        return {
            "requested": True,
            "created": False,
            "reason": f"not eligible: action is {decision.get('action')}",
        }

    if result.get("safety_warnings"):
        return {
            "requested": True,
            "created": False,
            "reason": "not eligible: safety warnings present",
        }

    if result.get("duplicate", {}).get("duplicate"):
        return {
            "requested": True,
            "created": False,
            "reason": f"not eligible: duplicate {result.get('duplicate', {}).get('id')}",
        }

    cleaned = result.get("cleaned_text", "").strip()
    if not cleaned:
        return {
            "requested": True,
            "created": False,
            "reason": "not eligible: empty filtered text",
        }

    candidate_tool = ROOT / "tools" / "memoria_memory_candidate_store.py"
    candidate_tags = [
        str(tag)
        for tag in result.get("suggested_tags", [])
        if str(tag) != "intake-dry-run"
    ]

    if "intake-candidate" not in candidate_tags:
        candidate_tags.append("intake-candidate")

    tags = ",".join(candidate_tags)
    metadata = result.get("candidate_metadata") or {}

    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
            tmp.write(cleaned)
            tmp_name = tmp.name

        command = [
            sys.executable,
            str(candidate_tool),
            "create",
            "--title",
            result.get("title", "Untitled memory candidate"),
            "--text-file",
            tmp_name,
            "--layer",
            decision.get("layer", "user"),
            "--source",
            "memory-intake",
            "--tags",
            tags,
        ]

        if metadata:
            command.extend([
                "--metadata-json",
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            ])

        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
        )

        output = completed.stdout
        match = re.search(r"CAND-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}", output)
        created = completed.returncode == 0 and match is not None

        return {
            "requested": True,
            "created": created,
            "candidate_id": match.group(0) if match else None,
            "exit_code": completed.returncode,
            "reason": "candidate stored for review" if created else "candidate store did not create item",
            "output": output,
        }

    finally:
        if tmp_name:
            try:
                Path(tmp_name).unlink()
            except FileNotFoundError:
                pass

def command_analyze(args: argparse.Namespace) -> int:
    text = args.text or ""

    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")

    result = analyze_text(text, user_declared_memory=args.user_declared_memory)

    if args.metadata_json:
        try:
            external_metadata = parse_metadata_json(
                args.metadata_json
            )
            result["candidate_metadata"] = (
                merge_candidate_metadata(
                    result.get(
                        "candidate_metadata"
                    ) or {},
                    external_metadata,
                )
            )
        except ValueError as e:
            if args.json:
                print(json.dumps({"error": str(e)}, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print(f"FAIL Memory Intake: {e}")
            return 2

    if args.create_candidate:
        creation = create_candidate_from_result(result)
        result["candidate_creation"] = creation
        if creation.get("created"):
            result["policy"]["candidate_written"] = True

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    print("## MEMORIA MEMORY INTAKE V0.3")
    print("------------------------------------------------------------")
    print("No private chat logs are scanned.")
    print(f"Candidate written: {'yes' if result['policy']['candidate_written'] else 'no'}")
    print("No durable memory is written.")
    print()
    print(f"Action: {result['decision']['action']}")
    print(f"Category: {result['decision']['category']}")
    print(f"Layer: {result['decision']['layer']}")
    print(f"Reason: {result['decision']['reason']}")
    print(f"Rule: {result['decision'].get('rule_id') or '-'}")
    print(f"Duplicate: {'yes' if result['duplicate'].get('duplicate') else 'no'}")
    if result["duplicate"].get("duplicate"):
        print(f"Duplicate ID: {result['duplicate'].get('id')}")
        print(f"Duplicate Type: {result['duplicate'].get('match_type')}")
    if result["safety_warnings"]:
        print("Safety Warnings:")
        for warning in result["safety_warnings"]:
            print(f"- {warning}")
    if result.get("candidate_creation"):
        creation = result["candidate_creation"]
        print(f"Candidate Create Requested: yes")
        print(f"Candidate Created: {'yes' if creation.get('created') else 'no'}")
        if creation.get("candidate_id"):
            print(f"Candidate ID: {creation.get('candidate_id')}")
        print(f"Candidate Create Reason: {creation.get('reason')}")

    print()
    print("Filtered Text:")
    print(result["cleaned_text"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MEMORIA memory intake dry-run scanner")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze")
    analyze.add_argument("--text", default="")
    analyze.add_argument("--text-file")
    analyze.add_argument("--json", action="store_true")
    analyze.add_argument("--create-candidate", action="store_true")
    analyze.add_argument("--metadata-json", default="")
    analyze.add_argument("--user-declared-memory", action="store_true")
    analyze.set_defaults(func=command_analyze)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
