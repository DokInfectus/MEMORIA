from pathlib import Path

# ==========================================================
# MEMORIA
# Version: 0.1.0
# Zentrale Konfiguration
# ==========================================================

# Basisverzeichnis
BASE_DIR = Path(__file__).resolve().parent

# Speicherorte
CONVERSATIONS_DIR = BASE_DIR / "conversations"
SUMMARIES_DIR = BASE_DIR / "summaries"
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
LOGS_DIR = BASE_DIR / "logs"

# Version
VERSION = "0.1.0"

# Standardmodell
DEFAULT_MODEL = "Gemma4-26B"

# Markdown speichern
SAVE_MARKDOWN = True

# JSON speichern
SAVE_JSON = True
