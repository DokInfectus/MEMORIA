from pathlib import Path
from typing import List

from config import BASE_DIR
from filesystem.manager import FilesystemManager
from history.exceptions import HistoryBuildError, HistoryLoadError


class HistoryManager:
    """
    Lädt Conversation-Dateien und erzeugt einen einfachen History-Kontext.
    """

    def __init__(self):
        self.base_dir = BASE_DIR / "conversations"
        self.fs = FilesystemManager()

    def load_recent_markdown(self, limit: int = 3) -> List[str]:
        try:
            files = sorted(
                self.base_dir.rglob("*.md"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )

            recent_files = files[:limit]

            return [
                self.fs.read_text(file)
                for file in recent_files
            ]

        except Exception as e:
            raise HistoryLoadError(str(e))

    def build_context(self, limit: int = 3) -> str:
        try:
            conversations = self.load_recent_markdown(limit=limit)

            if not conversations:
                return "=== CONVERSATION HISTORY ===\n\nKeine Conversation History vorhanden.\n\n============================"

            lines = [
                "=== CONVERSATION HISTORY ===",
                ""
            ]

            for index, conversation in enumerate(conversations, start=1):
                lines.append(f"--- Conversation {index} ---")
                lines.append(conversation.strip())
                lines.append("")

            lines.append("============================")

            return "\n".join(lines)

        except Exception as e:
            raise HistoryBuildError(str(e))
