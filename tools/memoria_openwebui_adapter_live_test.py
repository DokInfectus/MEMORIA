#!/usr/bin/env python3
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from adapter.exceptions import AdapterExecutionError
from adapter.openwebui import OpenWebUIAdapter


def line():
    print("-" * 40)


def section(title: str):
    print()
    print(f"## {title}")
    line()


def status(label: str, message: str, ok=None):
    prefix = "INFO"
    if ok is True:
        prefix = "OK  "
    elif ok is False:
        prefix = "FAIL"

    print(f"{prefix} {label}: {message}")


def main() -> int:
    section("MEMORIA OPENWEBUI ADAPTER LIVE TEST V0.1")
    print("Read-only adapter live test. No config changes. No private Open WebUI backup.")
    print("Token value is never printed.")

    try:
        adapter = OpenWebUIAdapter(
            base_url="http://127.0.0.1:8080",
            temperature=0.2,
        )

        section("Adapter")
        status("Adapter", "OpenWebUIAdapter", ok=True)
        status("API Key Source", adapter.api_key_source, ok=True)
        status("Token", "value is never printed", ok=True)

        model = adapter.resolve_model()
        status("Open WebUI Model", model, ok=True)

        section("Adapter Send")
        prompt = "Antworte kurz auf Deutsch: Was ist MEMORIA?"
        status("Prompt", prompt, ok=None)

        response = adapter.send(prompt)

        if not response.strip():
            status("OpenWebUIAdapter Response", "empty response", ok=False)
            return 1

        status("OpenWebUIAdapter Response", "received", ok=True)
        status("Response Text", response.strip(), ok=None)

        section("Result")
        status("OpenWebUIAdapter Live Test", "completed", ok=True)
        return 0

    except AdapterExecutionError as e:
        section("Result")
        status("OpenWebUIAdapter Live Test", str(e), ok=False)
        return 1

    except Exception as e:
        section("Result")
        status("OpenWebUIAdapter Live Test", str(e), ok=False)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
