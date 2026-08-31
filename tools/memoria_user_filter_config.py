#!/usr/bin/env python3
import argparse
import json
import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRESETS_FILE = PROJECT_ROOT / "config" / "rules" / "system" / "filter_presets.json"
ENABLED_PRESETS_FILE = PROJECT_ROOT / "config" / "rules" / "user" / "enabled_filter_presets.json"
DEFAULT_TERMS_FILE = PROJECT_ROOT / "config" / "rules" / "user" / "custom_important.txt"
DEFAULT_ATTACHMENT_FILTER_FILE = PROJECT_ROOT / "config" / "rules" / "user" / "attachment_memory_filter.json"

SENSITIVE_PATTERNS = [
    re.compile(r"api[_-]?key", re.I),
    re.compile(r"token", re.I),
    re.compile(r"password", re.I),
    re.compile(r"secret", re.I),
    re.compile(r"bearer\s+", re.I),
]


def terms_file() -> Path:
    return Path(os.environ.get("MEMORIA_CUSTOM_IMPORTANT_TERMS", str(DEFAULT_TERMS_FILE)))


def enabled_presets_file() -> Path:
    return Path(os.environ.get("MEMORIA_ENABLED_FILTER_PRESETS", str(ENABLED_PRESETS_FILE)))


def attachment_filter_file() -> Path:
    return Path(
        os.environ.get(
            "MEMORIA_ATTACHMENT_FILTER_CONFIG",
            str(DEFAULT_ATTACHMENT_FILTER_FILE),
        )
    )


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def normalize(term: str) -> str:
    return " ".join(term.strip().split())


def validate_term(term: str) -> str:
    term = normalize(term)

    if not term:
        raise ValueError("empty term is not allowed")
    if len(term) < 2:
        raise ValueError("term is too short")
    if len(term) > 120:
        raise ValueError("term is too long")

    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(term):
            raise ValueError("term looks like a secret/key/token marker and is not allowed")

    return term


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def read_terms(path: Path) -> list[str]:
    terms = []
    for line in read_lines(path):
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        terms.append(value)
    return terms


def write_lines(path: Path, lines: list[str]) -> None:
    ensure_parent(path)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_json_atomic(path: Path, data) -> None:
    ensure_parent(path)
    temporary = path.with_name(path.name + ".tmp")

    try:
        with temporary.open("w", encoding="utf-8") as handle:
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

        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_presets() -> dict:
    data = read_json(PRESETS_FILE, {"presets": []})
    presets = {}
    for item in data.get("presets", []):
        preset_id = item.get("id")
        if preset_id:
            presets[preset_id] = item
    return presets


def load_enabled() -> list[str]:
    data = read_json(enabled_presets_file(), {
        "schema_version": "memoria-enabled-filter-presets-v0.1",
        "enabled_presets": []
    })
    return list(data.get("enabled_presets", []))


def save_enabled(enabled: list[str]) -> None:
    unique = []
    seen = set()
    for item in enabled:
        if item not in seen:
            unique.append(item)
            seen.add(item)

    write_json(enabled_presets_file(), {
        "schema_version": "memoria-enabled-filter-presets-v0.1",
        "policy": {
            "enabled_presets_create_candidates_only": True,
            "no_direct_durable_memory": True
        },
        "enabled_presets": unique
    })



def default_attachment_filter() -> dict:
    return {
        "schema_version":
            "memoria-attachment-memory-filter-v0.1",
        "enabled": True,
        "policy": {
            "default_enabled": True,
            "explicit_user_attachments_only": True,
            "disabled_blocks_new_attachment_writes": True,
            "disabled_preserves_existing_attachments": True,
            "list_and_show_remain_available_when_disabled": True,
            "no_automatic_candidate": True,
            "no_automatic_durable_memory": True,
        },
    }


def load_attachment_filter() -> dict:
    path = attachment_filter_file()
    default = default_attachment_filter()

    if not path.exists():
        return default

    data = read_json(path, default)

    if not isinstance(data, dict):
        raise ValueError(
            "attachment filter config must be a JSON object"
        )

    enabled = data.get("enabled", True)

    if not isinstance(enabled, bool):
        raise ValueError(
            "attachment filter enabled must be true or false"
        )

    result = default_attachment_filter()
    result.update(data)
    result["enabled"] = enabled

    policy = result.get("policy")
    if not isinstance(policy, dict):
        raise ValueError(
            "attachment filter policy must be a JSON object"
        )

    return result


def attachment_memory_enabled() -> bool:
    return bool(
        load_attachment_filter().get("enabled", True)
    )


def save_attachment_filter(enabled: bool) -> None:
    data = default_attachment_filter()
    data["enabled"] = bool(enabled)

    write_json_atomic(
        attachment_filter_file(),
        data,
    )


def cmd_attachments_status(_args) -> int:
    path = attachment_filter_file()
    enabled = attachment_memory_enabled()

    print("MEMORIA ATTACHMENT-/BILD-ERINNERUNGEN V0.1")
    print("-" * 60)
    print(f"Enabled: {'yes' if enabled else 'no'}")
    print("Default: enabled")
    print(
        "Config exists: "
        f"{'yes' if path.exists() else 'no'}"
    )
    print(f"Config: {path}")
    print()
    print("Policy:")
    print("- Only explicitly supplied attachments may be stored.")
    print("- Disabled blocks new ATT-* writes.")
    print("- Existing ATT-* objects remain preserved.")
    print("- list/show remain read-only and available.")
    print("- No automatic Candidate or MEM-* is created.")

    return 0


def cmd_attachments_enable(_args) -> int:
    save_attachment_filter(True)

    print("OK Attachment-/Bild-Erinnerungen enabled")
    print(f"Path: {attachment_filter_file()}")
    print(
        "Policy: explicit attachments may be stored; "
        "no automatic memory is created."
    )

    return 0


def cmd_attachments_disable(_args) -> int:
    save_attachment_filter(False)

    print("OK Attachment-/Bild-Erinnerungen disabled")
    print(f"Path: {attachment_filter_file()}")
    print(
        "Policy: new ATT-* writes are blocked; "
        "existing attachments remain preserved."
    )

    return 0



def add_terms(path: Path, new_terms: list[str]) -> int:
    lines = read_lines(path)

    if not lines:
        lines = [
            "# MEMORIA user custom important terms",
            "# One term per line. Used by Memory Intake to create review candidates.",
            "# Do not store secrets, API keys, passwords or tokens here.",
            "",
        ]

    existing = {normalize(t).casefold() for t in read_terms(path)}
    added = 0

    for raw in new_terms:
        term = validate_term(raw)
        key = term.casefold()
        if key in existing:
            continue
        lines.append(term)
        existing.add(key)
        added += 1

    write_lines(path, lines)
    return added


def remove_terms(path: Path, remove_terms_: list[str]) -> int:
    wanted = {normalize(t).casefold() for t in remove_terms_ if normalize(t)}
    lines = read_lines(path)
    kept = []
    removed = 0

    for line in lines:
        value = line.strip()
        if value and not value.startswith("#") and normalize(value).casefold() in wanted:
            removed += 1
            continue
        kept.append(line)

    write_lines(path, kept)
    return removed


def cmd_custom_list(_args) -> int:
    path = terms_file()
    terms = read_terms(path)
    print(f"User custom important terms file: {path}")
    print(f"Terms: {len(terms)}")
    for index, term in enumerate(terms, start=1):
        print(f"{index:03d} {term}")
    return 0


def cmd_custom_add(args) -> int:
    path = terms_file()
    added = add_terms(path, args.term)
    print(f"OK added custom terms: {added}")
    print(f"Path: {path}")
    return 0


def cmd_custom_del(args) -> int:
    path = terms_file()
    removed = remove_terms(path, args.term)
    print(f"OK removed custom terms: {removed}")
    print(f"Path: {path}")
    return 0


def cmd_presets_list(_args) -> int:
    presets = load_presets()
    enabled = set(load_enabled())
    print(f"Filter presets file: {PRESETS_FILE}")
    print(f"Presets: {len(presets)}")
    for preset_id in sorted(presets):
        item = presets[preset_id]
        state = "enabled" if preset_id in enabled else "disabled"
        print(f"{preset_id:18} {state:8} {item.get('label', preset_id)}")
    return 0


def cmd_presets_show(args) -> int:
    presets = load_presets()
    item = presets.get(args.preset)
    if not item:
        print(f"ERROR unknown preset: {args.preset}")
        return 2

    print(f"Preset: {item['id']}")
    print(f"Label: {item.get('label', item['id'])}")
    print(f"Description: {item.get('description', '')}")
    print("Terms:")
    for term in item.get("terms", []):
        print(f"- {term}")
    return 0


def cmd_presets_enabled(_args) -> int:
    enabled = load_enabled()
    print(f"Enabled presets file: {enabled_presets_file()}")
    print(f"Enabled presets: {len(enabled)}")
    for item in enabled:
        print(f"- {item}")
    return 0


def cmd_presets_enable(args) -> int:
    presets = load_presets()
    if args.preset not in presets:
        print(f"ERROR unknown preset: {args.preset}")
        return 2

    enabled = load_enabled()
    if args.preset not in enabled:
        enabled.append(args.preset)
    save_enabled(enabled)

    print(f"OK enabled preset: {args.preset}")
    print(f"Path: {enabled_presets_file()}")
    return 0


def cmd_presets_disable(args) -> int:
    enabled = load_enabled()
    before = len(enabled)
    enabled = [item for item in enabled if item != args.preset]
    save_enabled(enabled)

    removed = before - len(enabled)
    print(f"OK disabled preset: {args.preset} removed={removed}")
    print(f"Path: {enabled_presets_file()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MEMORIA user filter configuration")
    sub = parser.add_subparsers(dest="command", required=True)

    custom = sub.add_parser("custom", help="Manage user custom important terms")
    custom_sub = custom.add_subparsers(dest="custom_command", required=True)

    p = custom_sub.add_parser("list", help="List custom terms")
    p.set_defaults(func=cmd_custom_list)

    p = custom_sub.add_parser("add", help="Add custom terms")
    p.add_argument("--term", action="append", required=True)
    p.set_defaults(func=cmd_custom_add)

    p = custom_sub.add_parser("del", help="Delete custom terms")
    p.add_argument("--term", action="append", required=True)
    p.set_defaults(func=cmd_custom_del)

    p = custom_sub.add_parser("remove", help="Delete custom terms")
    p.add_argument("--term", action="append", required=True)
    p.set_defaults(func=cmd_custom_del)

    presets = sub.add_parser("presets", help="Manage standard filter presets")
    presets_sub = presets.add_subparsers(dest="presets_command", required=True)

    p = presets_sub.add_parser("list", help="List presets")
    p.set_defaults(func=cmd_presets_list)

    p = presets_sub.add_parser("show", help="Show one preset")
    p.add_argument("preset")
    p.set_defaults(func=cmd_presets_show)

    p = presets_sub.add_parser("enabled", help="List enabled presets")
    p.set_defaults(func=cmd_presets_enabled)

    p = presets_sub.add_parser("enable", help="Enable preset")
    p.add_argument("preset")
    p.set_defaults(func=cmd_presets_enable)

    p = presets_sub.add_parser("disable", help="Disable preset")
    p.add_argument("preset")
    p.set_defaults(func=cmd_presets_disable)

    attachments = sub.add_parser(
        "attachments",
        help="Manage Attachment-/Bild-Erinnerungen",
    )
    attachments_sub = attachments.add_subparsers(
        dest="attachments_command",
        required=True,
    )

    p = attachments_sub.add_parser(
        "status",
        help="Show attachment memory filter status",
    )
    p.set_defaults(func=cmd_attachments_status)

    p = attachments_sub.add_parser(
        "enable",
        help="Enable explicit attachment storage",
    )
    p.set_defaults(func=cmd_attachments_enable)

    p = attachments_sub.add_parser(
        "disable",
        help="Disable new attachment storage",
    )
    p.set_defaults(func=cmd_attachments_disable)

    # Backward-compatible aliases from V0.1.
    p = sub.add_parser("list", help="Alias: custom list")
    p.set_defaults(func=cmd_custom_list)

    p = sub.add_parser("add", help="Alias: custom add")
    p.add_argument("--term", action="append", required=True)
    p.set_defaults(func=cmd_custom_add)

    p = sub.add_parser("remove", help="Alias: custom remove")
    p.add_argument("--term", action="append", required=True)
    p.set_defaults(func=cmd_custom_del)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        return args.func(args)
    except ValueError as exc:
        print(f"ERROR {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
