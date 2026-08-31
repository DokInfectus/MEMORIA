#!/usr/bin/env python3

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


CONFIG_PATH = Path("config/runtime.json")


def line():
    print("-" * 40)


def section(title):
    print()
    print(f"## {title}")
    line()


def status(label, message, ok=None):
    if ok is True:
        prefix = "OK  "
    elif ok is False:
        prefix = "FAIL"
    else:
        prefix = "INFO"

    print(f"{prefix} {label}: {message}")


def load_runtime_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("config/runtime.json not found")

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def require_text(config, key):
    value = config.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing or invalid field: {key}")

    return value.strip()


def build_chat_url(base_url):
    return base_url.rstrip("/") + "/v1/chat/completions"


def call_backend(base_url, model):
    url = build_chat_url(base_url)

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": "Say MEMORIA_OK",
            },
        ],
        "temperature": 0,
        "max_tokens": 64,
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

    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")

    parsed = json.loads(body)

    choices = parsed.get("choices", [])

    if not choices:
        raise ValueError("backend returned no choices")

    choice = choices[0]

    message = choice.get("message", {})
    content = message.get("content", "")

    if not isinstance(content, str):
        content = ""

    content = content.strip()

    if not content and isinstance(choice.get("text"), str):
        content = choice.get("text", "").strip()

    if not content:
        reasoning_content = message.get("reasoning_content", "")

        if isinstance(reasoning_content, str) and reasoning_content.strip():
            return "reasoning_content received; assistant content empty"

        raise ValueError("backend returned empty assistant content")

    return content


def main():
    section("MEMORIA RUNTIME SMOKE TEST")

    try:
        config = load_runtime_config()
        status("Runtime Config", "loaded", ok=True)
    except Exception as e:
        status("Runtime Config", str(e), ok=False)
        return 1

    try:
        setup_mode = require_text(config, "setup_mode")
        adapter = require_text(config, "adapter")
        base_url = require_text(config, "base_url")
        model = require_text(config, "model")
    except Exception as e:
        status("Runtime Config", str(e), ok=False)
        return 1

    status("Setup Mode", setup_mode, ok=True)
    status("Adapter", adapter, ok=True)
    status("Base URL", base_url, ok=True)
    status("Model", model, ok=True)

    section("Backend Request")

    if adapter != "LlamaCppAdapter":
        status(
            "Adapter",
            f"smoke test currently supports LlamaCppAdapter, got {adapter}",
            ok=False,
        )
        return 1

    try:
        response_text = call_backend(base_url, model)
        status("Backend Response", "received", ok=True)
        status("Backend Text", response_text, ok=None)
    except urllib.error.URLError as e:
        status("Backend Response", str(e), ok=False)
        status("Hint", "check whether llama.cpp is running and base_url is correct", ok=None)
        return 1
    except Exception as e:
        status("Backend Response", str(e), ok=False)
        return 1

    section("Result")
    status("Runtime", "ready", ok=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
