from typing import Dict, List, Optional, Tuple

from models.knowledge import Knowledge
from context.exceptions import EmptyContextError


class ContextBuilder:
    """
    Erstellt einen MEMORIA-Kontext aus Knowledge-Objekten.
    """

    def build(
        self,
        knowledge_list: List[Knowledge],
        max_entries: Optional[int] = None,
        max_characters: Optional[int] = None,
    ) -> str:

        context, _stats = self.build_with_stats(
            knowledge_list,
            max_entries=max_entries,
            max_characters=max_characters,
        )
        return context

    def build_with_stats(
        self,
        knowledge_list: List[Knowledge],
        max_entries: Optional[int] = None,
        max_characters: Optional[int] = None,
    ) -> Tuple[str, Dict[str, int]]:

        if not knowledge_list:
            raise EmptyContextError("Keine Knowledge-Einträge vorhanden.")

        lines = [
            "=== MEMORIA CONTEXT ===",
            ""
        ]

        used_entries = 0

        for item in knowledge_list:

            if max_entries is not None and used_entries >= max_entries:
                break

            block_lines = [
                f"[{item.category}]",
                item.title,
                item.content,
                ""
            ]

            candidate_lines = lines + block_lines + ["======================="]
            candidate_text = "\n".join(candidate_lines)

            if max_characters is not None and len(candidate_text) > max_characters:
                # This result does not fit, but a later smaller memory may fit.
                continue

            lines.extend(block_lines)
            used_entries += 1

        if used_entries == 0:
            raise EmptyContextError("Kein Knowledge-Eintrag passt in das Kontext-Budget.")

        lines.append("=======================")

        context = "\n".join(lines)

        return context, {
            "used_entries": used_entries,
        }
