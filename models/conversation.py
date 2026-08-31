from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Conversation:

    title: str

    content: str

    model: str = "Gemma4-26B"

    created: datetime = field(default_factory=datetime.now)

    version: str = "0.1.2"
