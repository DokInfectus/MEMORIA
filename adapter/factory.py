from typing import Any, Dict, Optional, Tuple

from adapter.base import BaseAdapter
from adapter.exceptions import AdapterExecutionError
from adapter.llamacpp import LlamaCppAdapter
from adapter.mock import MockAdapter
from adapter.openwebui import OpenWebUIAdapter
from adapter.ollama import OllamaAdapter


SUPPORTED_ADAPTERS = (
    "LlamaCppAdapter",
    "OpenWebUIAdapter",
    "OllamaAdapter",
    "MockAdapter",
)


def supported_adapters() -> Tuple[str, ...]:
    return SUPPORTED_ADAPTERS


def _text(config: Dict[str, Any], key: str, default: Optional[str] = None) -> Optional[str]:
    value = config.get(key, default)

    if value is None:
        return default

    text = str(value).strip()
    return text if text else default


def _int(config: Dict[str, Any], key: str, default: int) -> int:
    value = config.get(key, default)

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_int(config: Dict[str, Any], key: str) -> Optional[int]:
    if key not in config or config.get(key) is None:
        return None

    value = str(config.get(key)).strip()
    if not value:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(config: Dict[str, Any], key: str, default: float) -> float:
    value = config.get(key, default)

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_adapter(config: Dict[str, Any]) -> BaseAdapter:
    """
    Baut einen MEMORIA Adapter aus einer Runtime-ähnlichen Config.

    Safety:
    - keine Runtime-Datei wird verändert
    - keine Config wird geschrieben
    - keine Tokens werden gedruckt
    - OpenWebUIAdapter nutzt seinen eigenen sicheren Key Loader
    """

    adapter_name = _text(config, "adapter", "")

    if adapter_name == "LlamaCppAdapter":
        return LlamaCppAdapter(
            base_url=_text(config, "base_url", "http://127.0.0.1:3000"),
            model=_text(config, "model", "local-model"),
            temperature=_float(config, "temperature", 0.2),
            max_tokens=_int(config, "max_tokens", 512),
            timeout=_int(config, "timeout", 120),
        )

    if adapter_name == "OpenWebUIAdapter":
        return OpenWebUIAdapter(
            base_url=_text(config, "base_url", "http://127.0.0.1:8080"),
            model=_text(config, "model", None),
            temperature=_float(config, "temperature", 0.2),
            max_tokens=_optional_int(config, "max_tokens"),
            timeout=_int(config, "timeout", 120),
            api_key=_text(config, "api_key", None),
            api_key_file=_text(config, "api_key_file", None),
        )

    if adapter_name == "OllamaAdapter":
        return OllamaAdapter(
            base_url=_text(config, "base_url", "http://127.0.0.1:11434"),
            model=_text(config, "model", "local-model"),
            temperature=_float(config, "temperature", 0.2),
            max_tokens=_int(config, "max_tokens", 512),
            timeout=_int(config, "timeout", 120),
        )

    if adapter_name == "MockAdapter":
        return MockAdapter()

    raise AdapterExecutionError(
        f"Unsupported adapter: {adapter_name}. "
        f"Supported adapters: {', '.join(SUPPORTED_ADAPTERS)}"
    )
