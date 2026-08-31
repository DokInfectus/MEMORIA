from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class Decision:
    """
    Repräsentiert das Ergebnis einer MEMORIA Rule Engine Prüfung.
    """

    action: str

    category: str = ""

    rule_id: Optional[str] = None

    reason: str = ""

    confidence: float = 1.0

    metadata: Dict[str, str] = field(default_factory=dict)
