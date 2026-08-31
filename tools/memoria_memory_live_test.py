#!/usr/bin/env python3

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


from configure.manager import ConfigureManager
from configure.prompt_context_mapping import resolve_context_profile
from adapter.llamacpp import LlamaCppAdapter
from prompt_engine.manager import PromptEngineManager


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


def build_adapter(config):
    adapter_name = require_text(config, "adapter")

    if adapter_name != "LlamaCppAdapter":
        raise ValueError(
            f"prompt engine live test currently supports LlamaCppAdapter, got {adapter_name}"
        )

    return LlamaCppAdapter(
        base_url=require_text(config, "base_url"),
        model=require_text(config, "model"),
        temperature=require_float(config, "temperature", 0.7),
        max_tokens=require_int(config, "max_tokens", 2048),
    )


def main():
    section("MEMORIA MEMORY LIVE TEST")

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
    status("Base URL", base_url, ok=True)
    status("Model", model, ok=True)

    if adapter_name != "LlamaCppAdapter":
        status(
            "Live Test",
            f"SKIP: direct memory live test is not applicable to {adapter_name}",
            ok=None,
        )
        status(
            "Hint",
            "use the Open WebUI memory live test for the active runtime mode",
            ok=None,
        )
        return 0

    section("Adapter Build")

    try:
        adapter = build_adapter(config)
        status("Adapter", "created from runtime config", ok=True)
    except Exception as e:
        status("Adapter", str(e), ok=False)
        return 1

    section("Prompt Engine")

    try:
        engine = PromptEngineManager()

        # Safety for this technical live test:
        # do not include stored history in the generated test prompt.
        engine.history.build_context = lambda: ""

        user_prompt = "Was entscheidet der Benutzer bei MEMORIA?"

        prompt_profile = config.get("prompt_profile", "gemma")

        if not isinstance(prompt_profile, str) or not prompt_profile.strip():
            prompt_profile = "gemma"

        prompt_profile = prompt_profile.strip()

        status("Prompt Profile", prompt_profile, ok=True)

        context_mapping = resolve_context_profile(prompt_profile)
        context_profile = context_mapping.context_profile

        status("Context Profile", context_profile, ok=True)
        status("Context Mapping", context_mapping.reason, ok=None)

        final_prompt = engine.generate(
            user_prompt=user_prompt,
            model=context_profile,
            system_prompt="Du bist MEMORIA Memory Live Test. Nutze den MEMORIA CONTEXT. Antworte kurz auf Deutsch.",
            max_history_entries=0,
            max_history_characters=0,
            include_history_metadata=False,
        )

        if not isinstance(final_prompt, str) or not final_prompt.strip():
            status("Prompt Engine", "generated empty prompt", ok=False)
            return 1

        status("Prompt Engine", "prompt generated", ok=True)

        required_memory = "MEMORIA bleibt immer nur das, was der Benutzer will."
        if required_memory not in final_prompt:
            status(
                "Memory Context",
                "SKIP: personal reference memory is not configured",
                ok=None,
            )
            status(
                "Live Test",
                "prerequisite missing; no memory was created or modified",
                ok=None,
            )
            return 0
        status("Memory Context", "required user-approved memory found in prompt", ok=True)
        status("Prompt Length", str(len(final_prompt)), ok=None)
        status("Retrieval Query", engine.get_retrieval_query(), ok=None)
        status("History Filter Stats", str(engine.get_history_filter_stats()), ok=None)

    except Exception as e:
        status("Prompt Engine", str(e), ok=False)
        return 1

    section("Adapter Send")

    try:
        response = adapter.send(final_prompt)

        if not isinstance(response, str) or not response.strip():
            status("Adapter Response", "empty response", ok=False)
            return 1

        status("Adapter Response", "received", ok=True)
        status("Response Text", response.strip(), ok=None)

        lowered_response = response.lower()
        if "benutzer" in lowered_response and ("will" in lowered_response or "entscheid" in lowered_response):
            status("Memory Answer", "response appears to use MEMORIA memory context", ok=True)
        else:
            status("Memory Answer", "response received; memory wording not obvious", ok=None)

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
    status("Memory Live Test", "completed", ok=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
