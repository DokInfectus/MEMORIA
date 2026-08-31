import json

from config import BASE_DIR
from logger import logger


SYSTEM_DIR = BASE_DIR / "system"
COUNTER_FILE = SYSTEM_DIR / "session_counter.json"


class SessionIDGenerator:

    def __init__(self):
        SYSTEM_DIR.mkdir(parents=True, exist_ok=True)

        if not COUNTER_FILE.exists():
            with open(COUNTER_FILE, "w", encoding="utf-8") as file:
                json.dump({"next_id": 1}, file, indent=2)

    def next_id(self) -> str:
        with open(COUNTER_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        next_number = int(data["next_id"])
        session_id = f"MEM-{next_number:08d}"

        data["next_id"] = next_number + 1

        with open(COUNTER_FILE, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

        logger.info(f"Neue Session-ID erzeugt: {session_id}")

        return session_id
