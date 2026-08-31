import json
import urllib.error
import urllib.request

from adapter.base import BaseAdapter
from adapter.exceptions import AdapterExecutionError


class OllamaAdapter(BaseAdapter):
    """
    Adapter für Ollama /api/chat.

    Safety:
    - sendet nur den fertigen MEMORIA Prompt
    - liest keine Chats, Personas oder privaten Dateien
    - does not read chats, personas or private files
    - erzeugt keine Memories
    - nutzt stream=false für einfache JSON-Antworten
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "local-model",
        temperature: float = 0.2,
        max_tokens: int = 512,
        timeout: int = 120,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = int(max_tokens)
        self.timeout = int(timeout)

        if self.max_tokens < 1:
            raise AdapterExecutionError("Ollama max_tokens must be >= 1.")

    def _extract_assistant_content(self, result: dict) -> str:
        message = result.get("message", {})

        if isinstance(message, dict):
            content = message.get("content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()

            thinking = message.get("thinking", "")
            if isinstance(thinking, str) and thinking.strip():
                raise AdapterExecutionError(
                    "Ollama returned thinking, but no normal assistant content."
                )

        response = result.get("response", "")
        if isinstance(response, str) and response.strip():
            return response.strip()

        thinking = result.get("thinking", "")
        if isinstance(thinking, str) and thinking.strip():
            raise AdapterExecutionError(
                "Ollama returned thinking, but no normal assistant content."
            )

        error = result.get("error", "")
        if isinstance(error, str) and error.strip():
            raise AdapterExecutionError(f"Ollama error: {error.strip()}")

        top_keys = ", ".join(sorted(str(key) for key in result.keys()))
        raise AdapterExecutionError(
            f"Ollama response contains empty assistant content. Top-level keys: {top_keys}"
        )

    def send(self, prompt: str) -> str:
        url = f"{self.base_url}/api/chat"

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }

        data = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")

            result = json.loads(raw)
            return self._extract_assistant_content(result)

        except urllib.error.HTTPError as e:
            body = e.read(300).decode("utf-8", errors="replace")
            raise AdapterExecutionError(f"Ollama POST /api/chat failed: HTTP {e.code} {body}")

        except urllib.error.URLError as e:
            raise AdapterExecutionError(str(e))

        except AdapterExecutionError:
            raise

        except Exception as e:
            raise AdapterExecutionError(str(e))
