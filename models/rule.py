from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class Rule:
    """
    Repräsentiert eine Regel der MEMORIA Rule Engine.
    """

    id: str

    name: str

    enabled: bool = True

    priority: int = 100

    match: List[str] = field(default_factory=list)

    action: str = "ignore"

    category: str = ""

    metadata: Dict[str, str] = field(default_factory=dict)
