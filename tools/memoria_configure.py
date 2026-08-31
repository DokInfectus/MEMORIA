#!/usr/bin/env python3

import os
import sys


PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


from configure.validators import ValidationError, validate_model_name
from diagnostics.manager import DiagnosticsManager
from ui.terminal.screen import banner, section, status, note
from ui.terminal.prompt import ask_text, ask_yes_no
from ui.terminal.profile_prompt import ask_profile_selection
from ui.terminal.prompt_profile_prompt import ask_prompt_profile
from configure.final_validation import validate_final_configuration
from configure.manager import ConfigureManager


DEFAULT_MODEL = "local-model"


def get_recommendation(backends):
    llama_cpp = backends.get("llama_cpp", [])
    ollama = backends.get("ollama", [])
    open_webui = backends.get("open_webui", [])

    if llama_cpp:
        first = llama_cpp[0]
        return {
            "setup_mode": "llama-cpp-direct",
            "adapter": first.get("recommended_adapter", "LlamaCppAdapter"),
            "base_url": first.get("base_url", "http://127.0.0.1:3000"),
        }

    if ollama:
        first = ollama[0]
        return {
            "setup_mode": "ollama",
            "adapter": first.get("recommended_adapter", "OllamaAdapter"),
            "base_url": first.get("base_url", "http://127.0.0.1:11434"),
        }

    if open_webui:
        first = open_webui[0]
        return {
            "setup_mode": "open-webui",
            "adapter": first.get(
                "recommended_adapter",
                "OpenWebUIAdapter mit Auth",
            ),
            "base_url": first.get("base_url", "http://127.0.0.1:8080"),
        }

    return {
        "setup_mode": "manual-advanced",
        "adapter": "Manual",
        "base_url": "",
    }


def ask_model() -> str:
    section("Model Selection")

    use_default_model = ask_yes_no(
        f"Use default model '{DEFAULT_MODEL}'?",
        default=True,
    )

    if use_default_model:
        return validate_model_name(DEFAULT_MODEL)

    while True:
        model = ask_text("Enter model name", DEFAULT_MODEL)

        try:
            return validate_model_name(model)
        except ValidationError as e:
            status("Model", str(e), ok=False)
            note("Please enter a real model name or press Enter for default.")


def main() -> int:
    banner("MEMORIA USER CONFIGURATION WIZARD")

    diagnostics = DiagnosticsManager().run()
    backends = diagnostics.get("backends", {})

    recommendation = get_recommendation(backends)

    section("Detected Recommendation")
    status("Mode", recommendation["setup_mode"], ok=True)
    status("Adapter", recommendation["adapter"], ok=True)
    status("Base URL", recommendation["base_url"], ok=True)

    section("User Choice")

    use_recommendation = ask_yes_no(
        "Use detected recommendation?",
        default=True,
    )

    if use_recommendation:
        setup_mode = recommendation["setup_mode"]
        adapter = recommendation["adapter"]
        base_url = recommendation["base_url"]
    else:
        setup_mode = ask_text("Setup mode", recommendation["setup_mode"])
        adapter = ask_text("Adapter", recommendation["adapter"])
        base_url = ask_text("Base URL", recommendation["base_url"])

    model = ask_model()

    prompt_profile_summary = ask_prompt_profile(model)
    prompt_profile = prompt_profile_summary["prompt_profile"]

    profile_summary = ask_profile_selection()

    section("Summary")
    status("Setup mode", setup_mode, ok=True)
    status("Adapter", adapter, ok=True)
    status("Base URL", base_url, ok=True)
    status("Model", model, ok=True)
    status("Prompt Profile", prompt_profile, ok=True)
    status("Profile", profile_summary["profile"], ok=True)
    status("Context Length", str(profile_summary["context_length"]), ok=None)
    status("Response Tokens", str(profile_summary["response_tokens"]), ok=None)
    status("Memory Budget", str(profile_summary["memory_budget"]), ok=None)
    status("History Budget", str(profile_summary["history_budget"]), ok=None)
    status("Reserved Output", str(profile_summary["reserved_output"]), ok=None)

    validation_config = {
        "setup_mode": setup_mode,
        "adapter": adapter,
        "base_url": base_url,
        "model": model,
        "context_length": profile_summary["context_length"],
        "response_tokens": profile_summary["response_tokens"],
        "memory_budget": profile_summary["memory_budget"],
        "history_budget": profile_summary["history_budget"],
        "reserved_output": profile_summary["reserved_output"],
    }

    validation = validate_final_configuration(validation_config)

    section("Final Validation")

    if validation.is_ok():
        status("Validation", "configuration valid", ok=True)
    else:
        status("Validation", "configuration invalid", ok=False)

    for message in validation.errors:
        status("Error", message, ok=False)

    for message in validation.warnings:
        status("Warning", message, ok=None)

    for message in validation.info:
        note(message)

    section("Save Gate")

    config_saved = False
    loaded_config = None

    if validation.is_ok():
        status(
            "Save Gate",
            "configuration is valid and can be saved",
            ok=True,
        )

        save_now = ask_yes_no(
            "Save this runtime configuration now?",
            default=False,
        )

        if save_now:
            runtime_config = {
                "setup_mode": setup_mode,
                "adapter": adapter,
                "base_url": base_url,
                "model": model,
                "profile": profile_summary["profile"],
                "prompt_profile": prompt_profile,
                "context_length": profile_summary["context_length"],
                "max_tokens": profile_summary["response_tokens"],
                "memory_token_budget": profile_summary["memory_budget"],
                "history_token_budget": profile_summary["history_budget"],
                "reserved_output_tokens": profile_summary["reserved_output"],
                "temperature": 0.7,
                "top_p": 0.9,
                "repeat_penalty": 1.1,
                "history_enabled": True,
                "max_history_entries": 1000,
                "diagnostic_level": "standard",
            }

            configure_manager = ConfigureManager()

            overwrite = False
            skip_save = False

            if configure_manager.runtime_config_exists():
                status(
                    "Runtime Config",
                    "existing config found",
                    ok=None,
                )

                overwrite = ask_yes_no(
                    "Overwrite existing runtime config?",
                    default=False,
                )

                if not overwrite:
                    skip_save = True
                    status(
                        "Runtime Config",
                        "not overwritten by user choice",
                        ok=None,
                    )

            if not skip_save:
                try:
                    saved_config = configure_manager.save_runtime_config(
                        runtime_config,
                        overwrite=overwrite,
                    )

                    loaded_config = configure_manager.load_runtime_config()

                    config_saved = True

                    status(
                        "Runtime Config",
                        "saved and reloaded successfully",
                        ok=True,
                    )

                except Exception as e:
                    status(
                        "Runtime Config",
                        str(e),
                        ok=False,
                    )
        else:
            status(
                "Runtime Config",
                "not saved by user choice",
                ok=None,
            )

    else:
        status(
            "Save Gate",
            "saving blocked because final validation failed",
            ok=False,
        )
        note("Fix the configuration and run the wizard again.")
        note("No runtime configuration was written.")

    section("Result")

    if config_saved:
        status("Wizard", "configuration saved", ok=True)
        status("Config", "saved", ok=True)

        if loaded_config:
            status(
                "Config Path",
                "config/runtime.json",
                ok=True,
            )
            status(
                "Loaded Mode",
                loaded_config.get("setup_mode", "unknown"),
                ok=True,
            )
            status(
                "Loaded Model",
                loaded_config.get("model", "unknown"),
                ok=True,
            )
            status(
                "Loaded Prompt Profile",
                loaded_config.get("prompt_profile", "unknown"),
                ok=True,
            )

    elif validation.is_ok():
        status("Wizard", "completed without saving", ok=None)
        status("Config", "not saved", ok=None)
    else:
        status("Wizard", "completed with validation errors", ok=None)
        status("Config", "not saved", ok=None)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
