import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

from adapter.base import BaseAdapter
from adapter.exceptions import AdapterExecutionError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_KEY_FILE = PROJECT_ROOT / "config" / "secrets" / "openwebui_api_key"

TOKEN_SAFETY_NOTE = "Token value is never printed."
DEFAULT_MAX_TOKENS = 2048
MAX_TOKENS_ENV = "MEMORIA_OPENWEBUI_MAX_TOKENS"

MEMORIA_ORIGIN_PREFIX = "[[MEMORIA_ORIGIN:"
MEMORIA_ORIGIN_SUFFIX = "]]"
DEFAULT_REQUEST_ORIGIN = "internal-tool"
USER_MESSAGE_ORIGIN = "user-message"

KNOWN_REQUEST_ORIGINS = {
    USER_MESSAGE_ORIGIN,
    DEFAULT_REQUEST_ORIGIN,
    "big-archive-block",
    "big-archive-reducer",
    "system-test",
}


def normalize_request_origin(value: str | None) -> str:
    origin = str(value or "").strip()

    if origin in KNOWN_REQUEST_ORIGINS:
        return origin

    return DEFAULT_REQUEST_ORIGIN


def wrap_prompt_with_origin(
    prompt: str,
    origin: str | None,
) -> str:
    normalized = normalize_request_origin(origin)

    return (
        f"{MEMORIA_ORIGIN_PREFIX}"
        f"{normalized}"
        f"{MEMORIA_ORIGIN_SUFFIX}\n"
        f"{str(prompt)}"
    )


def read_api_key_file(path: Path) -> str:
    if not path.exists():
        return ""

    mode = path.stat().st_mode
    if mode & 0o077:
        raise AdapterExecutionError(
            f"Open WebUI API key file permissions are too open: {path}. Use chmod 600."
        )

    return path.read_text(encoding="utf-8").strip().strip('"').strip("'")


def resolve_max_tokens(value: Optional[int] = None) -> int:
    if value is not None:
        resolved = int(value)
    else:
        raw = os.environ.get(MAX_TOKENS_ENV, "").strip()
        resolved = int(raw) if raw else DEFAULT_MAX_TOKENS

    if resolved < 1:
        raise AdapterExecutionError("Open WebUI max_tokens must be >= 1.")

    return resolved


def load_api_key(
    api_key: Optional[str] = None,
    api_key_file: Optional[str] = None,
) -> Tuple[str, str]:
    explicit_key = (api_key or "").strip().strip('"').strip("'")
    if explicit_key:
        return explicit_key, "explicit"

    env_key = os.environ.get("MEMORIA_OPENWEBUI_API_KEY", "").strip().strip('"').strip("'")
    if env_key:
        return env_key, "environment"

    explicit_file = (api_key_file or "").strip()
    if explicit_file:
        key = read_api_key_file(Path(explicit_file).expanduser())
        if key:
            return key, "explicit-file"

    env_file = os.environ.get("MEMORIA_OPENWEBUI_API_KEY_FILE", "").strip()
    if env_file:
        key = read_api_key_file(Path(env_file).expanduser())
        if key:
            return key, "env-file"

    key = read_api_key_file(DEFAULT_API_KEY_FILE)
    if key:
        return key, "default-file"

    return "", "not-set"


class OpenWebUIAdapter(BaseAdapter):
    """
    Adapter für Open WebUI Chat Completions API.

    Safety:
    - reads API key from env or root-only key file
    - never prints token
    - does not read Open WebUI chats, prompts, personas or private folders
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        timeout: int = 120,
        api_key: Optional[str] = None,
        api_key_file: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = resolve_max_tokens(max_tokens)
        self.timeout = timeout
        self.api_key, self.api_key_source = load_api_key(api_key, api_key_file)
        self._resolved_model: Optional[str] = None

    def _headers(self) -> dict:
        if not self.api_key:
            raise AdapterExecutionError(
                "Open WebUI API key missing. Set MEMORIA_OPENWEBUI_API_KEY "
                "or use config/secrets/openwebui_api_key with chmod 600."
            )

        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _get_json(self, endpoint: str) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}{endpoint}",
            headers=self._headers(),
            method="GET",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            body = e.read(300).decode("utf-8", errors="replace")
            raise AdapterExecutionError(f"Open WebUI GET {endpoint} failed: HTTP {e.code} {body}")
        except urllib.error.URLError as e:
            raise AdapterExecutionError(str(e))
        except Exception as e:
            raise AdapterExecutionError(str(e))

    def _post_json(self, endpoint: str, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            f"{self.base_url}{endpoint}",
            data=data,
            headers=self._headers(),
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            body = e.read(300).decode("utf-8", errors="replace")
            raise AdapterExecutionError(f"Open WebUI POST {endpoint} failed: HTTP {e.code} {body}")
        except urllib.error.URLError as e:
            raise AdapterExecutionError(str(e))
        except Exception as e:
            raise AdapterExecutionError(str(e))

    def resolve_model(self) -> str:
        if self.model:
            return self.model

        if self._resolved_model:
            return self._resolved_model

        result = self._get_json("/api/models")
        models = result.get("data", [])

        if not isinstance(models, list) or not models:
            raise AdapterExecutionError("Open WebUI returned no models.")

        first = models[0]
        model_id = first.get("id") or first.get("name")

        if not isinstance(model_id, str) or not model_id.strip():
            raise AdapterExecutionError("Open WebUI model id missing.")

        self._resolved_model = model_id.strip()
        return self._resolved_model

    def _content_from_value(self, value) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()

        if isinstance(value, list):
            parts = []

            for part in value:
                if isinstance(part, str) and part.strip():
                    parts.append(part.strip())
                    continue

                if isinstance(part, dict):
                    for key in ("text", "content"):
                        nested = part.get(key)
                        if isinstance(nested, str) and nested.strip():
                            parts.append(nested.strip())

            return "\n".join(parts).strip()

        return ""

    def _extract_assistant_content(self, result: dict) -> str:
        choices = result.get("choices", [])

        if choices:
            choice = choices[0]
            message = choice.get("message", {})

            if isinstance(message, dict):
                content = self._content_from_value(message.get("content", ""))
                if content:
                    return content

                reasoning_content = self._content_from_value(message.get("reasoning_content", ""))
                if reasoning_content:
                    raise AdapterExecutionError(
                        "Open WebUI returned reasoning_content, but no normal assistant content."
                    )

            text = self._content_from_value(choice.get("text", ""))
            if text:
                return text

            delta = choice.get("delta", {})
            if isinstance(delta, dict):
                delta_content = self._content_from_value(delta.get("content", ""))
                if delta_content:
                    return delta_content

        root_response = self._content_from_value(result.get("response", ""))
        if root_response:
            return root_response

        root_message = result.get("message", {})
        if isinstance(root_message, dict):
            root_content = self._content_from_value(root_message.get("content", ""))
            if root_content:
                return root_content

        top_keys = ", ".join(sorted(str(key) for key in result.keys()))
        raise AdapterExecutionError(
            f"Open WebUI response contains empty assistant content. Top-level keys: {top_keys}"
        )

    def send(
        self,
        prompt: str,
        *,
        origin: str = DEFAULT_REQUEST_ORIGIN,
    ) -> str:
        model_id = self.resolve_model()
        marked_prompt = wrap_prompt_with_origin(
            prompt,
            origin,
        )

        payload = {
            "model": model_id,
            "messages": [
                {
                    "role": "user",
                    "content": marked_prompt,
                }
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }

        result = self._post_json("/api/chat/completions", payload)
        return self._extract_assistant_content(result)
