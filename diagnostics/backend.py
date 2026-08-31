import json
import urllib.error
import urllib.request
from typing import Any, Dict, List

from diagnostics.exceptions import BackendDiagnosticsError


class BackendDiagnostics:
    """
    Erkennt lokale LLM-Backends.

    V1:
    - llama.cpp
    - Open WebUI
    - Ollama

    LM Studio wird bewusst noch nicht erkannt.
    Es wird später als eigener Diagnosebaustein ergänzt.
    """

    def run(self) -> Dict[str, Any]:
        try:
            return {
                "llama_cpp": self.check_llama_cpp(),
                "open_webui": self.check_open_webui(),
                "ollama": self.check_ollama(),
            }
        except Exception as e:
            raise BackendDiagnosticsError(str(e))

    def check_llama_cpp(self) -> List[Dict[str, Any]]:
        results = []

        for port in [3000, 8080, 8081, 5000, 8000, 1234]:
            base_url = f"http://127.0.0.1:{port}"

            health = self._request(f"{base_url}/health")
            models = self._request(f"{base_url}/v1/models")

            is_openai_compatible = (
                models["ok"]
                and isinstance(models["json"], dict)
                and "data" in models["json"]
            )

            # Wichtig:
            # llama.cpp wird nur dann als Adapter-Ziel erkannt,
            # wenn /v1/models OpenAI-kompatibel antwortet.
            # Ein reiner /health Treffer reicht nicht aus,
            # weil Open WebUI ebenfalls Health-Endpunkte liefern kann.
            if is_openai_compatible:
                results.append(
                    {
                        "type": "llama.cpp",
                        "base_url": base_url,
                        "port": port,
                        "health_ok": health["ok"],
                        "openai_compatible": True,
                        "recommended_adapter": "LlamaCppAdapter",
                    }
                )

        return results

    def check_open_webui(self) -> List[Dict[str, Any]]:
        results = []

        for port in [8080, 3000]:
            base_url = f"http://127.0.0.1:{port}"

            root = self._request(f"{base_url}/")
            api_models = self._request(f"{base_url}/api/models")

            looks_like_open_webui = (
                root["ok"]
                and isinstance(root["text"], str)
                and "Open WebUI" in root["text"]
            )

            auth_required = (
                api_models["status"] in [401, 403]
                or (
                    isinstance(api_models["json"], dict)
                    and "not authenticated" in json.dumps(api_models["json"]).lower()
                )
            )

            if looks_like_open_webui or auth_required:
                results.append(
                    {
                        "type": "open_webui",
                        "base_url": base_url,
                        "port": port,
                        "reachable": True,
                        "auth_required": auth_required,
                        "recommended_adapter": (
                            "OpenWebUIAdapter mit Auth"
                            if auth_required
                            else "OpenWebUIAdapter"
                        ),
                    }
                )

        return results

    def check_ollama(self) -> List[Dict[str, Any]]:
        results = []

        for port in [11434]:
            base_url = f"http://127.0.0.1:{port}"

            tags = self._request(f"{base_url}/api/tags")

            if tags["ok"] and isinstance(tags["json"], dict):
                results.append(
                    {
                        "type": "ollama",
                        "base_url": base_url,
                        "port": port,
                        "reachable": True,
                        "recommended_adapter": "OllamaAdapter",
                    }
                )

        return results

    def _request(self, url: str) -> Dict[str, Any]:
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json, text/html, */*",
                },
            )

            with urllib.request.urlopen(request, timeout=2) as response:
                status = response.status
                raw = response.read().decode("utf-8", errors="replace")

            return self._format_response(
                ok=200 <= status < 300,
                status=status,
                text=raw,
            )

        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")

            return self._format_response(
                ok=False,
                status=e.code,
                text=raw,
            )

        except Exception:
            return {
                "ok": False,
                "status": None,
                "text": "",
                "json": None,
            }

    def _format_response(
        self,
        ok: bool,
        status: Any,
        text: str,
    ) -> Dict[str, Any]:
        parsed_json = None

        try:
            parsed_json = json.loads(text)
        except Exception:
            parsed_json = None

        return {
            "ok": ok,
            "status": status,
            "text": text,
            "json": parsed_json,
        }
