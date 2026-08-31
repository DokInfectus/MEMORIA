#!/usr/bin/env python3
"""
MEMORIA Memory Lifecycle Menu V0.1

Human-facing MEM-* enable/disable test menu.
No delete. No forget. No MEM archive here.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / "tools"

for item in [str(PROJECT_ROOT), str(TOOLS_DIR)]:
    if item not in sys.path:
        sys.path.insert(0, item)

from memoria_storage_paths import managed_path


MEMORY_DIR = managed_path(
    "memory",
    env_var="MEMORIA_MEMORY_DIR",
    fallback_rel="knowledge/memory",
)


def load_records():
    records = []

    if not MEMORY_DIR.exists():
        return records

    for path in sorted(MEMORY_DIR.glob("MEM-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"WARN skipped {path.name}: {exc}")
            continue

        record_id = str(data.get("id", path.stem))
        if not record_id.startswith("MEM-"):
            continue

        records.append((path, data))

    return records


def compact(text, limit=96):
    value = " ".join(str(text or "").split())
    return value[:limit] + ("..." if len(value) > limit else "")


def print_records(records):
    if not records:
        print("INFO keine MEM-* Erinnerungen gefunden.")
        return

    print()
    print("## Gespeicherte Erinnerungen")
    print("-" * 100)
    for index, (_path, data) in enumerate(records, start=1):
        record_id = str(data.get("id", ""))
        status = str(data.get("status", "active"))
        title = compact(data.get("title") or "-", 76)
        preview = compact(data.get("content") or data.get("text") or "", 110)
        tags = ", ".join(data.get("tags", [])[:4]) if data.get("tags") else "-"

        print(f"{index:>3}) [{status:<8}] {record_id[-8:]}  {title}")
        if preview:
            print(f"     Text : {preview}")
        print(f"     Tags : {tags}")
    print()
    print("Auswahl-Beispiele: 2 | 2,5,7 | 1-10 | all | alle")


def resolve_selection(selection, records):
    value = str(selection or "").strip()

    if not value:
        raise ValueError("keine Auswahl eingegeben")

    if value.lower() in {"all", "alle", "*"}:
        return records

    selected = []
    seen = set()

    tokens = []
    for part in value.replace(",", " ").split():
        tokens.append(part.strip())

    for token in tokens:
        if not token:
            continue

        if "-" in token and all(piece.strip().isdigit() for piece in token.split("-", 1)):
            left, right = token.split("-", 1)
            start = int(left)
            end = int(right)

            if start < 1 or end < start or end > len(records):
                raise ValueError(f"ungültiger Bereich: {token}")

            for number in range(start, end + 1):
                record = records[number - 1]
                record_id = str(record[1].get("id", ""))
                if record_id not in seen:
                    selected.append(record)
                    seen.add(record_id)
            continue

        if token.isdigit():
            number = int(token)
            if number < 1 or number > len(records):
                raise ValueError(f"Nummer außerhalb der Liste: {token}")

            record = records[number - 1]
            record_id = str(record[1].get("id", ""))
            if record_id not in seen:
                selected.append(record)
                seen.add(record_id)
            continue

        if len(token) < 5:
            raise ValueError("ID/Suffix muss mindestens 5 Zeichen haben")

        matches = []
        for record in records:
            record_id = str(record[1].get("id", ""))
            if record_id == token or record_id.endswith(token):
                matches.append(record)

        if not matches:
            raise ValueError(f"keine Erinnerung passt zu: {token}")

        if len(matches) > 1:
            ids = ", ".join(str(item[1].get("id", "")) for item in matches[:10])
            raise ValueError(f"Auswahl nicht eindeutig: {token}; Treffer: {ids}")

        record = matches[0]
        record_id = str(record[1].get("id", ""))
        if record_id not in seen:
            selected.append(record)
            seen.add(record_id)

    return selected


def confirm_all_if_needed(selection, new_status, count):
    if str(selection or "").strip().lower() not in {"all", "alle", "*"}:
        return True

    phrase = "ALLE DEAKTIVIEREN" if new_status == "disabled" else "ALLE AKTIVIEREN"

    print()
    print(f"Du willst {count} Erinnerungen auf {new_status} setzen.")
    print("Das löscht nichts, aber es ändert sofort, was Retrieval/KI nutzen darf.")
    confirm = input(f"Zum Bestätigen exakt eingeben: {phrase}: ").strip()

    return confirm == phrase


def set_status(selection, new_status):
    records = load_records()
    targets = resolve_selection(selection, records)

    if not targets:
        print("INFO keine Ziele ausgewählt.")
        return 0

    print()
    print("## Ausgewählte Erinnerungen")
    print("-" * 80)
    for _path, data in targets:
        print(f"- {data.get('id')} | {data.get('status', 'active')} | {compact(data.get('title') or data.get('content') or '-', 90)}")

    if not confirm_all_if_needed(selection, new_status, len(targets)):
        print("ABBRUCH Bestätigung passt nicht.")
        return 1

    now = datetime.now().isoformat()
    for path, data in targets:
        old_status = str(data.get("status", "active"))
        data["status"] = new_status
        data["updated"] = now

        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        print(f"OK {data.get('id')} : {old_status} -> {new_status}")

    print()
    print("Policy: Datei bleibt erhalten. Retrieval nutzt nur active MEM-*.")
    return 0


def show_full(selection):
    records = load_records()
    targets = resolve_selection(selection, records)

    for _path, data in targets:
        print()
        print("-" * 80)
        print(f"ID     : {data.get('id')}")
        print(f"Status : {data.get('status', 'active')}")
        print(f"Title  : {data.get('title', '-')}")
        print(f"Tags   : {', '.join(data.get('tags', [])) if data.get('tags') else '-'}")
        print(f"Source : {data.get('source_session', '-')}")
        print("Text   :")
        print(data.get("content", ""))

    return 0


def retrieval_test(query):
    from retrieval.manager import RetrievalManager

    hits = RetrievalManager().search(query)

    print()
    print(f"QUERY: {query}")
    print(f"HITS : {len(hits)}")
    for item in hits:
        print(f"- {item.id} | {item.title}")

    return 0


def self_test():
    records = [
        (Path("a"), {"id": "MEM-20260716-000001-aaaa1111"}),
        (Path("b"), {"id": "MEM-20260716-000002-bbbb2222"}),
        (Path("c"), {"id": "MEM-20260716-000003-cccc3333"}),
    ]

    assert [r[1]["id"] for r in resolve_selection("1", records)] == [records[0][1]["id"]]
    assert [r[1]["id"] for r in resolve_selection("1,3", records)] == [records[0][1]["id"], records[2][1]["id"]]
    assert [r[1]["id"] for r in resolve_selection("1-2", records)] == [records[0][1]["id"], records[1][1]["id"]]
    assert len(resolve_selection("all", records)) == 3
    assert resolve_selection("b2222", records)[0][1]["id"] == records[1][1]["id"]

    print("Memory Lifecycle Number Selection V0.1 Self-Test OK")


def main():
    while True:
        print()
        print("## MEM Lifecycle / Erinnerungen aktivieren-deaktivieren")
        print("-" * 60)
        print("1  Erinnerungen nummeriert anzeigen")
        print("2  Erinnerung vollständig anzeigen")
        print("3  Erinnerung deaktivieren")
        print("4  Erinnerung aktivieren")
        print("5  Retrieval-Test ausführen")
        print("0  Zurück")
        print()
        print("Auswahl kann Nummer, Liste, Bereich oder all sein:")
        print("  2 | 2,5,7 | 1-10 | all | alle")
        print()
        print("Policy:")
        print("- active = KI/Retrieval darf die Erinnerung nutzen.")
        print("- disabled = bleibt gespeichert, KI/Retrieval ignoriert sie.")
        print("- Kein Archivieren, Löschen oder Forget in diesem Menü.")
        print()

        choice = input("Auswahl: ").strip()

        if choice == "0":
            return 0

        if choice == "1":
            print_records(load_records())
        elif choice == "2":
            records = load_records()
            print_records(records)
            selection = input("Nummer/ID/Suffix anzeigen: ").strip()
            if selection:
                show_full(selection)
        elif choice == "3":
            records = load_records()
            print_records(records)
            selection = input("Deaktivieren Nummer/Liste/Bereich/all: ").strip()
            if selection:
                set_status(selection, "disabled")
        elif choice == "4":
            records = load_records()
            print_records(records)
            selection = input("Aktivieren Nummer/Liste/Bereich/all: ").strip()
            if selection:
                set_status(selection, "active")
        elif choice == "5":
            query = input("Retrieval Suchbegriff: ").strip()
            if query:
                retrieval_test(query)
        else:
            print("Ungültige Auswahl.")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        raise SystemExit(0)

    raise SystemExit(main())
