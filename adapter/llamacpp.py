import json
import urllib.request
import urllib.error

from adapter.base import BaseAdapter
from adapter.exceptions import AdapterExecutionError


class LlamaCppAdapter(BaseAdapter):
    """
    Adapter für llama.cpp OpenAI-kompatible Chat Completions API.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:3000",
        model: str = "local",
        temperature: float = 0.2,
        max_tokens: int = 512,
        timeout: int = 120,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def _extract_assistant_content(self, result: dict) -> str:
        choices = result.get("choices", [])

        if not choices:
            raise AdapterExecutionError(
                "llama.cpp Antwort enthält keine choices."
            )

        choice = choices[0]

        message = choice.get("message", {})

        if not isinstance(message, dict):
            raise AdapterExecutionError(
                "llama.cpp Antwort enthält keine gültige message."
            )

        content = message.get("content", "")

        if isinstance(content, str) and content.strip():
            return content.strip()

        text = choice.get("text", "")

        if isinstance(text, str) and text.strip():
            return text.strip()

        reasoning_content = message.get("reasoning_content", "")

        if isinstance(reasoning_content, str) and reasoning_content.strip():
            raise AdapterExecutionError(
                "llama.cpp lieferte reasoning_content, aber keine normale assistant content Antwort."
            )

        raise AdapterExecutionError(
            "llama.cpp Antwort enthält leeren assistant content."
        )


    def send(self, prompt: str) -> str:
        url = f"{self.base_url}/v1/chat/completions"

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        data = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
            ) as response:
                raw = response.read().decode("utf-8")

            result = json.loads(raw)

            return self._extract_assistant_content(result)

        except urllib.error.URLError as e:
            raise AdapterExecutionError(str(e))

        except Exception as e:
            raise AdapterExecutionError(str(e))
