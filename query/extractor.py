import re
from typing import Dict, List

from query.exceptions import QueryExtractionError


class QueryExtractor:
    """
    Extrahiert einen neutralen Suchkern aus einer Benutzerfrage.

    V1:
    - regelbasiert
    - keine Blackbox
    - keine Persona-Interpretation
    - keine fest verdrahteten Benutzerrollen
    """

    KEYWORDS: Dict[str, List[str]] = {
        "RTX": [
            "rtx",
            "2080",
            "2080ti",
            "2080 ti",
            "nvidia",
        ],
        "VRAM": [
            "vram",
            "videospeicher",
            "grafikspeicher",
            "speicher",
        ],
        "GPU": [
            "gpu",
            "grafikkarte",
            "grafikkarten",
            "karte",
            "karten",
        ],
        "hardware": [
            "hardware",
            "server",
            "rechner",
            "system",
        ],
    }

    def extract(self, user_prompt: str) -> str:
        """
        Gibt einen Suchbegriff für Retrieval zurück.
        """

        try:
            normalized = self._normalize(user_prompt)

            for canonical, variants in self.KEYWORDS.items():
                for variant in variants:
                    if self._contains_term(normalized, variant):
                        return canonical

            return user_prompt.strip()

        except Exception as e:
            raise QueryExtractionError(str(e))

    def _normalize(self, text: str) -> str:
        text = text.lower()
        text = text.replace("-", " ")
        text = text.replace("_", " ")
        text = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß ]+", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _contains_term(self, text: str, term: str) -> bool:
        term = term.lower().strip()
        pattern = r"(^| )" + re.escape(term) + r"($| )"
        return re.search(pattern, text) is not None
