#!/usr/bin/env python3

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


from configure.manager import ConfigureManager
from adapter.factory import build_adapter, supported_adapters


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


def require_text(config, key):
    value = config.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing or invalid field: {key}")

    return value.strip()


def require_int(config, key, default):
    value = config.get(key, default)

    if isinstance(value, bool):
        raise ValueError(f"invalid boolean field: {key}")

    if isinstance(value, int):
        return value

    try:
        return int(value)
    except Exception:
        raise ValueError(f"missing or invalid integer field: {key}")


def require_float(config, key, default):
    value = config.get(key, default)

    if isinstance(value, bool):
        raise ValueError(f"invalid boolean field: {key}")

    if isinstance(value, (int, float)):
        return float(value)

    try:
        return float(value)
    except Exception:
        raise ValueError(f"missing or invalid float field: {key}")


def main():
    section("MEMORIA ADAPTER LIVE TEST")

    manager = ConfigureManager()

    try:
        config = manager.load_runtime_config()
        status("Runtime Config", "loaded", ok=True)
    except Exception as e:
        status("Runtime Config", str(e), ok=False)
        return 1

    try:
        setup_mode = require_text(config, "setup_mode")
        adapter_name = require_text(config, "adapter")
        base_url = require_text(config, "base_url")
        model = require_text(config, "model")
    except Exception as e:
        status("Runtime Config", str(e), ok=False)
        return 1

    status("Setup Mode", setup_mode, ok=True)
    status("Adapter", adapter_name, ok=True)
    status("Supported Adapters", ", ".join(supported_adapters()), ok=True)
    status("Base URL", base_url, ok=True)
    status("Model", model, ok=True)

    section("Adapter Build")

    try:
        adapter = build_adapter(config)
        status("Adapter", "created from runtime config", ok=True)
    except Exception as e:
        status("Adapter", str(e), ok=False)
        return 1

    section("Adapter Send")

    prompt = "Say MEMORIA_OK"

    status("Prompt", prompt, ok=None)

    try:
        response = adapter.send(prompt)

        if not isinstance(response, str) or not response.strip():
            status("Adapter Response", "empty response", ok=False)
            return 1

        status("Adapter Response", "received", ok=True)
        status("Response Text", response.strip(), ok=None)

    except Exception as e:
        message = str(e)

        if "reasoning_content" in message and "assistant content" in message:
            status(
                "Adapter Response",
                "backend reached, but model returned reasoning_content without assistant content",
                ok=None,
            )
            status(
                "Hint",
                "adapter correctly refused to expose reasoning_content as normal chat output",
                ok=True,
            )
        else:
            status("Adapter Response", message, ok=False)
            return 1

    section("Result")
    status("Adapter Live Test", "completed", ok=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
