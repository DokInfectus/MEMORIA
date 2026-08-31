from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Knowledge:
    """
    Repräsentiert eine einzelne Wissenseinheit in MEMORIA.
    """

    id: str
    title: str
    category: str
    content: str

    tags: List[str] = field(default_factory=list)
    status: str = "active"
    source_session: Optional[str] = None

    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    version: str = "0.1.7"

    @classmethod
    def from_dict(cls, data: dict):
        """
        Erzeugt ein Knowledge-Objekt aus einer JSON-Struktur.
        """

        created = data.get("created")
        updated = data.get("updated")

        if isinstance(created, str):
            created = datetime.fromisoformat(created)

        if isinstance(updated, str):
            updated = datetime.fromisoformat(updated)

        return cls(
            id=data["id"],
            title=data["title"],
            category=data["category"],
            content=data["content"],
            tags=data.get("tags", []),
            status=data.get("status", "active"),
            source_session=data.get("source_session"),
            created=created or datetime.now(),
            updated=updated or datetime.now(),
            version=data.get("version", "0.1.7"),
        )
