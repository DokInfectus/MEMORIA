from typing import Dict, List, Optional


class HistoryFilter:
    """
    Filtert Conversation History für den Prompt-Kontext.

    V2.1:
    - entfernt leere Zeilen
    - entfernt direkte doppelte Zeilen
    - kann Metadaten optional entfernen
    - begrenzt optional die Anzahl der Conversation-Blöcke
    - begrenzt optional die Zeichenanzahl
    - sammelt einfache Statistikdaten
    """

    def __init__(self):
        self.stats: Dict[str, int] = {}

    def reset_stats(self) -> None:
        self.stats = {
            "empty_lines_removed": 0,
            "duplicates_removed": 0,
            "metadata_lines_removed": 0,
            "entries_removed": 0,
            "characters_before": 0,
            "characters_after": 0,
        }

    def get_stats(self) -> Dict[str, int]:
        return dict(self.stats)

    def filter_text(
        self,
        text: str,
        max_entries: Optional[int] = None,
        max_characters: Optional[int] = None,
        include_metadata: bool = True,
    ) -> str:

        self.reset_stats()
        self.stats["characters_before"] = len(text)

        cleaned = self._clean_text(text)

        if not include_metadata:
            cleaned = self._remove_metadata(cleaned)

        limited_entries = self._limit_entries(cleaned, max_entries)

        limited_characters = self._limit_characters(
            limited_entries,
            max_characters,
        )

        self.stats["characters_after"] = len(limited_characters)

        return limited_characters

    def _clean_text(self, text: str) -> str:
        lines = text.splitlines()

        filtered: List[str] = []
        previous = None

        for line in lines:
            clean = line.strip()

            if not clean:
                self.stats["empty_lines_removed"] += 1
                continue

            if clean == previous:
                self.stats["duplicates_removed"] += 1
                continue

            filtered.append(clean)
            previous = clean

        return "\n".join(filtered)

    def _remove_metadata(self, text: str) -> str:
        lines = text.splitlines()

        filtered: List[str] = []
        in_metadata = False

        for line in lines:
            clean = line.strip()

            if clean == "# MEMORIA Conversation":
                self.stats["metadata_lines_removed"] += 1
                continue

            if clean == "## Metadata":
                in_metadata = True
                self.stats["metadata_lines_removed"] += 1
                continue

            if in_metadata:
                if clean == "## Conversation":
                    in_metadata = False
                    self.stats["metadata_lines_removed"] += 1
                    continue

                self.stats["metadata_lines_removed"] += 1
                continue

            if clean == "## Conversation":
                self.stats["metadata_lines_removed"] += 1
                continue

            if clean == "---":
                self.stats["metadata_lines_removed"] += 1
                continue

            filtered.append(clean)

        return "\n".join(filtered)

    def _split_conversations(self, text: str) -> List[str]:
        parts = text.split("--- Conversation ")

        if len(parts) == 1:
            return [text] if text.strip() else []

        conversations: List[str] = []

        prefix = parts[0].strip()

        for part in parts[1:]:
            conversations.append("--- Conversation " + part.strip())

        if prefix and not prefix.startswith("=== CONVERSATION HISTORY ==="):
            conversations.insert(0, prefix)

        return conversations

    def _limit_entries(
        self,
        text: str,
        max_entries: Optional[int],
    ) -> str:

        if max_entries is None:
            return text

        conversations = self._split_conversations(text)

        if len(conversations) <= max_entries:
            return text

        removed = len(conversations) - max_entries
        self.stats["entries_removed"] += removed

        selected = conversations[-max_entries:]

        header = "=== CONVERSATION HISTORY ==="

        if text.startswith(header):
            return "\n".join([header] + selected)

        return "\n".join(selected)

    def _limit_characters(
        self,
        text: str,
        max_characters: Optional[int],
    ) -> str:

        if max_characters is None:
            return text

        if len(text) <= max_characters:
            return text

        conversations = self._split_conversations(text)
        header = "=== CONVERSATION HISTORY ==="

        selected: List[str] = []

        for conversation in reversed(conversations):
            candidate = "\n".join(
                [header] + list(reversed(selected + [conversation]))
            )

            if len(candidate) <= max_characters:
                selected.append(conversation)

        selected = list(reversed(selected))

        removed = len(conversations) - len(selected)
        self.stats["entries_removed"] += removed

        if selected:
            return "\n".join([header] + selected)

        return header
