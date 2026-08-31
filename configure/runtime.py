import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

from configure.exceptions import (
    RuntimeConfigReadError,
    RuntimeConfigValidationError,
    RuntimeConfigWriteError,
)


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

DEFAULT_RUNTIME_CONFIG_PATH = os.path.join(
    PROJECT_ROOT,
    "config",
    "runtime.json",
)


ALLOWED_KEYS = {
    "setup_mode",
    "adapter",
    "base_url",
    "model",
    "temperature",
    "max_tokens",
    "context_length",
    "top_p",
    "repeat_penalty",
    "history_enabled",
    "max_history_entries",
    "diagnostic_level",
    "profile",
    "prompt_profile",
    "memory_token_budget",
    "history_token_budget",
    "reserved_output_tokens",
    "created_at",
    "updated_at",
}


ALLOWED_SETUP_MODES = {
    "llama-cpp-direct",
    "open-webui",
    "ollama",
    "manual-advanced",
}


ALLOWED_DIAGNOSTIC_LEVELS = {
    "off",
    "standard",
    "verbose",
}


DEFAULTS = {
    "temperature": 0.7,
    "max_tokens": 2048,
    "context_length": 32768,
    "top_p": 0.9,
    "repeat_penalty": 1.1,
    "history_enabled": True,
    "max_history_entries": 1000,
    "diagnostic_level": "standard",
    "profile": "balanced",
    "memory_token_budget": 4096,
    "history_token_budget": 2048,
    "reserved_output_tokens": 2048,
}


FORBIDDEN_KEY_PARTS = {
    "password",
    "secret",
    "api_key",
    "apikey",
    "private_chat",
    "persona",
    "chat_history",
    "memory_content",
}


class RuntimeConfigManager:
    """
    Verwaltet die lokale MEMORIA Runtime-Konfiguration.

    Erlaubt sind nur technische Laufzeitdaten.
    Keine privaten Chats, keine Personas, keine Tokens,
    keine Passwoerter und keine vollstaendigen Prompts.
    """

    def __init__(self, config_path: str = DEFAULT_RUNTIME_CONFIG_PATH):
        self.config_path = config_path

    def build_runtime_config(
        self,
        setup_mode: str,
        adapter: str,
        base_url: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        context_length: int = 32768,
        top_p: float = 0.9,
        repeat_penalty: float = 1.1,
        history_enabled: bool = True,
        max_history_entries: int = 1000,
        diagnostic_level: str = "standard",
    ) -> Dict[str, Any]:
        config = {
            "setup_mode": setup_mode,
            "adapter": adapter,
            "base_url": base_url,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "context_length": context_length,
            "top_p": top_p,
            "repeat_penalty": repeat_penalty,
            "history_enabled": history_enabled,
            "max_history_entries": max_history_entries,
            "diagnostic_level": diagnostic_level,
        }

        return self.validate(config)

    def exists(self) -> bool:
        return os.path.exists(self.config_path)

    def load(self) -> Dict[str, Any]:
        try:
            with open(self.config_path, "r", encoding="utf-8") as file:
                data = json.load(file)

            return self.validate(data)

        except FileNotFoundError as e:
            raise RuntimeConfigReadError(
                f"Runtime config not found: {self.config_path}"
            ) from e

        except Exception as e:
            raise RuntimeConfigReadError(str(e)) from e

    def save(
        self,
        config: Dict[str, Any],
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        try:
            validated = self.validate(config)

            if self.exists() and not overwrite:
                raise RuntimeConfigWriteError(
                    "Runtime config already exists. "
                    "Refusing to overwrite without explicit confirmation."
                )

            now = datetime.now(timezone.utc).isoformat()
            created_at = validated.get("created_at")

            if self.exists():
                try:
                    existing = self.load()
                    created_at = existing.get("created_at", created_at)
                except Exception:
                    pass

            if not created_at:
                created_at = now

            validated["created_at"] = created_at
            validated["updated_at"] = now

            config_dir = os.path.dirname(self.config_path)
            os.makedirs(config_dir, exist_ok=True)

            temp_path = f"{self.config_path}.tmp"

            with open(temp_path, "w", encoding="utf-8") as file:
                json.dump(
                    validated,
                    file,
                    indent=4,
                    ensure_ascii=False,
                )
                file.write("\n")

            os.replace(temp_path, self.config_path)

            return validated

        except RuntimeConfigWriteError:
            raise

        except Exception as e:
            raise RuntimeConfigWriteError(str(e)) from e

    def validate(self, config: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(config, dict):
            raise RuntimeConfigValidationError(
                "Runtime config must be a dictionary."
            )

        self._check_forbidden_fields(config)

        unknown_keys = set(config.keys()) - ALLOWED_KEYS

        if unknown_keys:
            raise RuntimeConfigValidationError(
                f"Unknown runtime config keys: {sorted(unknown_keys)}"
            )

        required_keys = {
            "setup_mode",
            "adapter",
            "base_url",
            "model",
        }

        missing_keys = required_keys - set(config.keys())

        if missing_keys:
            raise RuntimeConfigValidationError(
                f"Missing runtime config keys: {sorted(missing_keys)}"
            )

        normalized = dict(DEFAULTS)
        normalized.update(config)

        normalized["setup_mode"] = str(normalized["setup_mode"]).strip()
        normalized["adapter"] = str(normalized["adapter"]).strip()
        normalized["base_url"] = str(normalized["base_url"]).strip()
        normalized["model"] = str(normalized["model"]).strip()

        if normalized["setup_mode"] not in ALLOWED_SETUP_MODES:
            raise RuntimeConfigValidationError(
                f"Invalid setup_mode: {normalized['setup_mode']}"
            )

        if not normalized["adapter"]:
            raise RuntimeConfigValidationError("adapter must not be empty.")

        if not normalized["base_url"]:
            raise RuntimeConfigValidationError("base_url must not be empty.")

        if not normalized["model"]:
            raise RuntimeConfigValidationError("model must not be empty.")

        normalized["temperature"] = self._to_float(
            normalized["temperature"],
            "temperature",
        )

        if normalized["temperature"] < 0.0:
            raise RuntimeConfigValidationError(
                "temperature must not be negative."
            )

        if normalized["temperature"] > 2.0:
            raise RuntimeConfigValidationError(
                "temperature must not be greater than 2.0."
            )

        normalized["max_tokens"] = self._to_int(
            normalized["max_tokens"],
            "max_tokens",
        )

        if normalized["max_tokens"] < 1:
            raise RuntimeConfigValidationError(
                "max_tokens must be greater than 0."
            )

        normalized["context_length"] = self._to_int(
            normalized["context_length"],
            "context_length",
        )

        if normalized["context_length"] < 1:
            raise RuntimeConfigValidationError(
                "context_length must be greater than 0."
            )

        normalized["top_p"] = self._to_float(
            normalized["top_p"],
            "top_p",
        )

        if normalized["top_p"] <= 0.0:
            raise RuntimeConfigValidationError(
                "top_p must be greater than 0.0."
            )

        if normalized["top_p"] > 1.0:
            raise RuntimeConfigValidationError(
                "top_p must not be greater than 1.0."
            )

        normalized["repeat_penalty"] = self._to_float(
            normalized["repeat_penalty"],
            "repeat_penalty",
        )

        if normalized["repeat_penalty"] <= 0.0:
            raise RuntimeConfigValidationError(
                "repeat_penalty must be greater than 0.0."
            )

        normalized["history_enabled"] = self._to_bool(
            normalized["history_enabled"],
            "history_enabled",
        )

        normalized["max_history_entries"] = self._to_int(
            normalized["max_history_entries"],
            "max_history_entries",
        )

        if normalized["max_history_entries"] < 0:
            raise RuntimeConfigValidationError(
                "max_history_entries must not be negative."
            )

        normalized["diagnostic_level"] = str(
            normalized["diagnostic_level"]
        ).strip()

        if normalized["diagnostic_level"] not in ALLOWED_DIAGNOSTIC_LEVELS:
            raise RuntimeConfigValidationError(
                "Invalid diagnostic_level: "
                f"{normalized['diagnostic_level']}"
            )

        return normalized

    def _to_float(self, value: Any, field_name: str) -> float:
        try:
            return float(value)
        except Exception as e:
            raise RuntimeConfigValidationError(
                f"{field_name} must be a number."
            ) from e

    def _to_int(self, value: Any, field_name: str) -> int:
        try:
            return int(value)
        except Exception as e:
            raise RuntimeConfigValidationError(
                f"{field_name} must be an integer."
            ) from e

    def _to_bool(self, value: Any, field_name: str) -> bool:
        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            text = value.strip().lower()

            if text in {"true", "yes", "y", "1", "on"}:
                return True

            if text in {"false", "no", "n", "0", "off"}:
                return False

        raise RuntimeConfigValidationError(
            f"{field_name} must be a boolean."
        )

    def _check_forbidden_fields(self, value: Any) -> None:
        if not isinstance(value, dict):
            return

        for key in value.keys():
            key_text = str(key).lower().replace("-", "_")

            for forbidden in FORBIDDEN_KEY_PARTS:
                if forbidden in key_text:
                    raise RuntimeConfigValidationError(
                        f"Forbidden runtime config field: {key}"
                    )
