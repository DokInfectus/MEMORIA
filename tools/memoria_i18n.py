#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from memoria_language_config import (
    DEFAULT_LANGUAGE,
    load_config,
    normalize_language,
)


TRANSLATIONS: dict[str, dict[str, str]] = {
    "de": {
        "common.back": "Zurück",
        "common.cancel": "Abbrechen",
        "common.yes": "ja",
        "common.no": "nein",
        "common.invalid_selection": "Ungültige Auswahl.",
        "common.selection": "Auswahl: ",
        "common.aborted": "Abgebrochen.",
        "common.answer_yes_no": "Bitte ja oder nein eingeben.",

        "trash.security": "Sicherheit:",
        "trash.confirm_move_disabled": (
            "Alle deaktivierten Erinnerungen in den "
            "Papierkorb verschieben? [ja/nein]: "
        ),
        "trash.memory_ref_prompt": (
            "MEM-ID oder eindeutige Endung eingeben, "
            "mindestens 5 Zeichen: "
        ),
        "trash.confirm_suffix_prompt": (
            "Zur endgültigen Löschung die letzten "
            "5+ Zeichen wiederholen: "
        ),
        "trash.invalid_ref": (
            "ID oder Endung muss mindestens 5 Zeichen haben."
        ),
        "trash.invalid_confirmation": (
            "Bestätigung muss mindestens 5 Zeichen haben."
        ),
        "trash.warning_purge_all": (
            "WARNUNG: Diese Aktion löscht alle Erinnerungen "
            "im Papierkorb endgültig."
        ),
        "trash.active_not_affected": (
            "Aktive Erinnerungen sind nicht betroffen."
        ),
        "trash.no_change": (
            "Papierkorb wurde nicht verändert."
        ),
        "trash.memories_found": (
            "{count} gespeicherte Erinnerungen gefunden."
        ),
        "trash.trash_items_found": (
            "{count} Erinnerungen im Papierkorb."
        ),
        "trash.empty_memories": (
            "Keine gespeicherten Erinnerungen gefunden."
        ),
        "trash.empty_trash": "Der Papierkorb ist leer.",
        "trash.choose_memory": (
            "Erinnerung auswählen "
            "(0 = abbrechen): "
        ),
        "trash.choose_trash_item": (
            "Papierkorb-Eintrag auswählen "
            "(0 = abbrechen): "
        ),
        "trash.invalid_number": (
            "Bitte eine gültige Nummer auswählen."
        ),
        "trash.selected_memory": (
            "Ausgewählte Erinnerung:"
        ),
        "trash.selected_trash_item": (
            "Ausgewählter Papierkorb-Eintrag:"
        ),
        "trash.item_title": "Titel: {title}",
        "trash.item_status": "Status: {status}",
        "trash.item_preview": "Vorschau: {preview}",
        "trash.item_reason": "Grund: {reason}",
        "trash.move_success": (
            "Erinnerung wurde in den Papierkorb verschoben."
        ),
        "trash.purge_success": (
            "Erinnerung wurde endgültig "
            "aus dem Papierkorb gelöscht."
        ),
        "trash.move_disabled_success": (
            "{count} deaktivierte Erinnerungen wurden "
            "in den Papierkorb verschoben."
        ),
        "trash.purge_all_success": (
            "Papierkorb wurde vollständig geleert."
        ),
        "trash.purge_all_count": (
            "Endgültig gelöschte Erinnerungen: {count}"
        ),
        "trash.core_failed": (
            "Die Aktion konnte nicht ausgeführt werden."
        ),
        "status.active": "aktiv",
        "status.disabled": "deaktiviert",
        "status.archived": "archiviert",
        "status.trashed": "im Papierkorb",

        "big_archive.ready_title": (
            "Fertige Gedächtnisarchive"
        ),
        "big_archive.none_ready": (
            "Kein fertiges, gültiges Gedächtnisarchiv gefunden."
        ),
        "big_archive.ready_found": (
            "{count} fertige Gedächtnisarchive gefunden."
        ),
        "big_archive.source": "Quelle: {name}",
        "big_archive.sections": (
            "Sektionen: {count}"
        ),
        "big_archive.readable_chars": (
            "Lesbarer Inhalt: {count} Zeichen"
        ),
        "big_archive.status": "Status: {status}",
        "big_archive.status_ready": "bereit",
        "big_archive.status_candidate": (
            "bereits im Review-Becken"
        ),
        "big_archive.status_promoted": (
            "bereits dauerhaft eingebunden"
        ),
        "big_archive.choose": (
            "Gedächtnisarchiv auswählen "
            "(0 = abbrechen): "
        ),
        "big_archive.invalid_number": (
            "Bitte eine gültige Nummer auswählen."
        ),
        "big_archive.read_only_note": (
            "Diese Ansicht ist read-only. "
            "Es wird noch kein Candidate oder MEM geschrieben."
        ),
        "big_archive.import_option": (
            "Fertiges Archiv als eine Gedächtnisdatei einbinden"
        ),
        "big_archive.import_title": (
            "Fertiges Gedächtnisarchiv einbinden"
        ),
        "big_archive.size_bytes": (
            "Quelldatei: {count} Bytes"
        ),
        "big_archive.source_chars": (
            "Quelltext: {count} Zeichen"
        ),
        "big_archive.technical_chunks": (
            "Technische Chunks: {count}"
        ),
        "big_archive.source_sections": (
            "Quellblöcke: {count}"
        ),
        "big_archive.archive_sections": (
            "Lesbare Archivkapitel: {count}"
        ),
        "big_archive.result_one": (
            "Ergebnis: genau eine Gedächtnisdatei"
        ),
        "big_archive.source_retained": (
            "Quelle, Archiv und Checkpoints bleiben erhalten."
        ),
        "big_archive.confirm_store": (
            "Diese Gedächtnisdatei jetzt dauerhaft "
            "speichern? [ja/nein]: "
        ),
        "big_archive.prepare_failed": (
            "Vorbereitung fehlgeschlagen: {error}"
        ),
        "big_archive.invalid_prepare": (
            "Die Vorbereitung lieferte ungültige Daten."
        ),
        "big_archive.already_promoted": (
            "Dieses Archiv wurde bereits dauerhaft eingebunden."
        ),
        "big_archive.cancel_removed": (
            "Nicht gespeichert. Der neu erzeugte "
            "Review-Eintrag wurde entfernt."
        ),
        "big_archive.cancel_preserved": (
            "Nicht gespeichert. Ein bereits vorhandener "
            "Review-Eintrag blieb unverändert."
        ),
        "big_archive.cleanup_failed": (
            "Der neu erzeugte Review-Eintrag konnte "
            "nicht entfernt werden."
        ),
        "big_archive.approve_failed": (
            "Die Freigabe der Gedächtnisdatei ist fehlgeschlagen."
        ),
        "big_archive.promote_failed": (
            "Die dauerhafte Speicherung ist fehlgeschlagen."
        ),
        "big_archive.approved_not_promoted": (
            "Der Review-Eintrag bleibt freigegeben; "
            "es wurde kein MEM erzeugt."
        ),
        "big_archive.postcheck_failed": (
            "Die abschließende Speicherprüfung ist fehlgeschlagen."
        ),
        "big_archive.saved": (
            "Gedächtnis wurde dauerhaft gespeichert: {memory_id}"
        ),

        "trash.title": "Erinnerungen löschen / Papierkorb",
        "trash.show_memories": "Gespeicherte Erinnerungen anzeigen",
        "trash.move_one": "Eine Erinnerung in den Papierkorb verschieben",
        "trash.move_disabled": (
            "Alle deaktivierten Erinnerungen "
            "in den Papierkorb verschieben"
        ),
        "trash.show": "Papierkorb anzeigen",
        "trash.purge_one": (
            "Eine Erinnerung endgültig "
            "aus dem Papierkorb löschen"
        ),
        "trash.purge_all": "Papierkorb vollständig leeren",

        "trash.policy.active_safe": (
            "Aktive Erinnerungen werden niemals "
            "direkt endgültig gelöscht."
        ),
        "trash.policy.hard_delete_only_trash": (
            "Endgültiges Löschen ist nur "
            "aus dem Papierkorb möglich."
        ),
        "trash.policy.no_automatic_empty": (
            "Der Papierkorb wird niemals automatisch geleert."
        ),

        "trash.confirm_move": (
            "Diese Erinnerung in den Papierkorb "
            "verschieben? [ja/nein]: "
        ),
        "trash.confirm_purge_one": (
            "Diese Erinnerung endgültig löschen? "
            "[ja/nein]: "
        ),
        "trash.confirm_purge_all": (
            "Alle Erinnerungen im Papierkorb "
            "endgültig löschen? [ja/nein]: "
        ),
        "trash.confirm_phrase_prompt": (
            "Zum endgültigen Löschen exakt "
            "{phrase} eingeben: "
        ),
        "trash.confirm_phrase": "PAPIERKORB-LEEREN",
    },

    "en": {
        "common.back": "Back",
        "common.cancel": "Cancel",
        "common.yes": "yes",
        "common.no": "no",
        "common.invalid_selection": "Invalid selection.",
        "common.selection": "Selection: ",
        "common.aborted": "Cancelled.",
        "common.answer_yes_no": "Please enter yes or no.",

        "trash.security": "Safety:",
        "trash.confirm_move_disabled": (
            "Move all disabled memories to trash? "
            "[yes/no]: "
        ),
        "trash.memory_ref_prompt": (
            "Enter a full MEM ID or unique suffix, "
            "at least 5 characters: "
        ),
        "trash.confirm_suffix_prompt": (
            "Repeat the last 5+ characters to "
            "permanently delete: "
        ),
        "trash.invalid_ref": (
            "ID or suffix must contain at least 5 characters."
        ),
        "trash.invalid_confirmation": (
            "Confirmation must contain at least 5 characters."
        ),
        "trash.warning_purge_all": (
            "WARNING: This permanently deletes all memories "
            "currently in trash."
        ),
        "trash.active_not_affected": (
            "Active memories are not affected."
        ),
        "trash.no_change": (
            "Memory trash was not changed."
        ),
        "trash.memories_found": (
            "{count} stored memories found."
        ),
        "trash.trash_items_found": (
            "{count} memories in trash."
        ),
        "trash.empty_memories": (
            "No stored memories found."
        ),
        "trash.empty_trash": "Memory trash is empty.",
        "trash.choose_memory": (
            "Select a memory "
            "(0 = cancel): "
        ),
        "trash.choose_trash_item": (
            "Select a trash item "
            "(0 = cancel): "
        ),
        "trash.invalid_number": (
            "Please select a valid number."
        ),
        "trash.selected_memory": (
            "Selected memory:"
        ),
        "trash.selected_trash_item": (
            "Selected trash item:"
        ),
        "trash.item_title": "Title: {title}",
        "trash.item_status": "Status: {status}",
        "trash.item_preview": "Preview: {preview}",
        "trash.item_reason": "Reason: {reason}",
        "trash.move_success": (
            "Memory was moved to trash."
        ),
        "trash.purge_success": (
            "Memory was permanently deleted from trash."
        ),
        "trash.move_disabled_success": (
            "{count} disabled memories were moved to trash."
        ),
        "trash.purge_all_success": (
            "Memory trash was emptied."
        ),
        "trash.purge_all_count": (
            "Permanently deleted memories: {count}"
        ),
        "trash.core_failed": (
            "The action could not be completed."
        ),
        "status.active": "active",
        "status.disabled": "disabled",
        "status.archived": "archived",
        "status.trashed": "in trash",

        "big_archive.ready_title": (
            "Completed memory archives"
        ),
        "big_archive.none_ready": (
            "No completed valid memory archive was found."
        ),
        "big_archive.ready_found": (
            "{count} completed memory archives found."
        ),
        "big_archive.source": "Source: {name}",
        "big_archive.sections": (
            "Sections: {count}"
        ),
        "big_archive.readable_chars": (
            "Readable content: {count} characters"
        ),
        "big_archive.status": "Status: {status}",
        "big_archive.status_ready": "ready",
        "big_archive.status_candidate": (
            "already in the review pool"
        ),
        "big_archive.status_promoted": (
            "already stored as durable memory"
        ),
        "big_archive.choose": (
            "Select a memory archive "
            "(0 = cancel): "
        ),
        "big_archive.invalid_number": (
            "Please select a valid number."
        ),
        "big_archive.read_only_note": (
            "This view is read-only. "
            "No Candidate or MEM is written yet."
        ),
        "big_archive.import_option": (
            "Import a completed archive as one memory file"
        ),
        "big_archive.import_title": (
            "Import completed memory archive"
        ),
        "big_archive.size_bytes": (
            "Source file: {count} bytes"
        ),
        "big_archive.source_chars": (
            "Source text: {count} characters"
        ),
        "big_archive.technical_chunks": (
            "Technical chunks: {count}"
        ),
        "big_archive.source_sections": (
            "Source blocks: {count}"
        ),
        "big_archive.archive_sections": (
            "Readable archive sections: {count}"
        ),
        "big_archive.result_one": (
            "Result: exactly one memory file"
        ),
        "big_archive.source_retained": (
            "Source, archive and checkpoints are retained."
        ),
        "big_archive.confirm_store": (
            "Store this memory file permanently now? "
            "[yes/no]: "
        ),
        "big_archive.prepare_failed": (
            "Preparation failed: {error}"
        ),
        "big_archive.invalid_prepare": (
            "Preparation returned invalid data."
        ),
        "big_archive.already_promoted": (
            "This archive has already been stored as durable memory."
        ),
        "big_archive.cancel_removed": (
            "Not stored. The newly created review entry was removed."
        ),
        "big_archive.cancel_preserved": (
            "Not stored. A pre-existing review entry was preserved."
        ),
        "big_archive.cleanup_failed": (
            "The newly created review entry could not be removed."
        ),
        "big_archive.approve_failed": (
            "Approving the memory file failed."
        ),
        "big_archive.promote_failed": (
            "Durable memory storage failed."
        ),
        "big_archive.approved_not_promoted": (
            "The review entry remains approved; no MEM was created."
        ),
        "big_archive.postcheck_failed": (
            "The final memory verification failed."
        ),
        "big_archive.saved": (
            "Memory was stored permanently: {memory_id}"
        ),

        "trash.title": "Delete memories / Memory trash",
        "trash.show_memories": "Show stored memories",
        "trash.move_one": "Move one memory to trash",
        "trash.move_disabled": (
            "Move all disabled memories to trash"
        ),
        "trash.show": "Show memory trash",
        "trash.purge_one": (
            "Permanently delete one memory from trash"
        ),
        "trash.purge_all": "Empty memory trash",

        "trash.policy.active_safe": (
            "Active memories are never permanently "
            "deleted directly."
        ),
        "trash.policy.hard_delete_only_trash": (
            "Permanent deletion is only possible "
            "from memory trash."
        ),
        "trash.policy.no_automatic_empty": (
            "Memory trash is never emptied automatically."
        ),

        "trash.confirm_move": (
            "Move this memory to trash? [yes/no]: "
        ),
        "trash.confirm_purge_one": (
            "Permanently delete this memory? "
            "[yes/no]: "
        ),
        "trash.confirm_purge_all": (
            "Permanently delete all memories "
            "in trash? [yes/no]: "
        ),
        "trash.confirm_phrase_prompt": (
            "Type {phrase} exactly to permanently delete: "
        ),
        "trash.confirm_phrase": "EMPTY-MEMORY-TRASH",
    },
}


YES_VALUES = {
    "de": {"ja", "j", "yes", "y"},
    "en": {"yes", "y", "ja", "j"},
}

NO_VALUES = {
    "de": {"nein", "n", "no"},
    "en": {"no", "n", "nein"},
}


def current_language() -> str:
    try:
        config = load_config()
        return normalize_language(
            str(config.get("language", DEFAULT_LANGUAGE))
        )
    except Exception:
        return DEFAULT_LANGUAGE


def text(
    key: str,
    *,
    language: str | None = None,
    **values: Any,
) -> str:
    lang = (
        normalize_language(language)
        if language is not None
        else current_language()
    )

    value = TRANSLATIONS.get(lang, {}).get(key)

    if value is None:
        value = TRANSLATIONS["en"].get(key)

    if value is None:
        return f"[{key}]"

    return value.format(**values)


def is_yes(
    value: str,
    *,
    language: str | None = None,
) -> bool:
    lang = (
        normalize_language(language)
        if language is not None
        else current_language()
    )
    return value.strip().lower() in YES_VALUES[lang]


def is_no(
    value: str,
    *,
    language: str | None = None,
) -> bool:
    lang = (
        normalize_language(language)
        if language is not None
        else current_language()
    )
    return value.strip().lower() in NO_VALUES[lang]


def validate_catalog() -> list[str]:
    errors: list[str] = []
    expected = set(TRANSLATIONS["en"])

    for language, catalog in TRANSLATIONS.items():
        missing = sorted(expected - set(catalog))
        extra = sorted(set(catalog) - expected)

        if missing:
            errors.append(
                f"{language}: missing={','.join(missing)}"
            )

        if extra:
            errors.append(
                f"{language}: extra={','.join(extra)}"
            )

        for key, value in catalog.items():
            if not str(value).strip():
                errors.append(
                    f"{language}: empty={key}"
                )

    return errors
