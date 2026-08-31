import json
import re
import sys
from pathlib import Path
from typing import List

from config import BASE_DIR

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from memoria_storage_paths import managed_path
from models.knowledge import Knowledge
from retrieval.exceptions import RetrievalLoadError


class RetrievalManager:
    """
    Lädt und durchsucht gespeicherte Knowledge-Objekte.
    """

    def __init__(self):
        # MEMORIA: durable memory may live on a selected storage root,
        # for example a user-selected storage root ending in knowledge/memory.
        # Retrieval must use approved/promoted memory, not the old project-local basin.
        self.base_dir = managed_path(
            "memory",
            env_var="MEMORIA_MEMORY_DIR",
            fallback_rel="knowledge/memory",
        )

    def load_all(self) -> List[Knowledge]:
        knowledge_list: List[Knowledge] = []

        try:
            for file in sorted(self.base_dir.rglob("*.json")):
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # MEMORIA: memory candidates are a review basin, not durable retrieval memory.
                if data.get("schema_version") == "memory-candidate-v0.1" or str(data.get("id", "")).startswith("CAND-"):
                    continue
                # MEMORIA: durable MEM-* lifecycle guard.
                # Only active memories may enter retrieval/prompt context.
                lifecycle_status = str(data.get("status") or data.get("lifecycle_state") or "active").lower()
                if lifecycle_status != "active":
                    continue

                knowledge_list.append(Knowledge.from_dict(data))

            return knowledge_list

        except Exception as e:
            raise RetrievalLoadError(str(e))

    def load_by_category(self, category: str) -> List[Knowledge]:
        """
        Lädt alle Knowledge-Objekte einer Kategorie.
        """

        category = category.lower()

        return [
            item
            for item in self.load_all()
            if item.category.lower() == category
        ]

    def _tokens(self, text: str) -> List[str]:
        """
        Zerlegt eine Suchanfrage in einfache        Zerlegt eine Suchanfrage in einfache Suchbegriffe.
        Keine KI, keine externe Suche, nur lokale deterministische Token-Suche.
        """

        stopwords = {
            "der", "die", "das", "den", "dem", "des",
            "ein", "eine", "einer", "und", "oder",
            "bei", "mit", "für", "von", "was", "wie",
            "ist", "sind", "wer", "wenn", "dann",
        }

        tokens = re.findall(r"[a-zA-ZÄÖÜäöüß0-9_]+", text.lower())

        return [
            token
            for token in tokens
            if len(token) >= 3 and token not in stopwords
        ]

    def search(self, query: str) -> List[Knowledge]:
        """
        Lokale Volltextsuche über Titel, Inhalt und Tags.

        V0.2:
        - exakter Treffer bleibt möglich
        - zusätzlich Token-Suche für natürliche Fragen
        - Ergebnisse werden nach Trefferzahl sortiert
        """

        query = query.lower().strip()
        query_tokens = self._tokens(query)
        scored_results = []

        for item in self.load_all():
            title = item.title.lower()
            content = item.content.lower()
            tags = " ".join(item.tags).lower()
            category = item.category.lower()

            haystack = " ".join([title, content, tags, category])

            score = 0

            if query and query in haystack:
                score += 100

            for token in query_tokens:
                if token in title:
                    score += 5
                if token in tags:
                    score += 4
                if token in category:
                    score += 3
                if token in content:
                    score += 2

            if score > 0:
                scored_results.append((score, item.title.lower(), item))

        scored_results.sort(key=lambda entry: (-entry[0], entry[1]))

        return [item for _score, _title, item in scored_results]
