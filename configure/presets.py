from copy import deepcopy


DEFAULT_MODEL = "local-model"


DEFAULT_LLM_SETTINGS = {
    "temperature": 0.7,
    "max_tokens": 2048,
    "context_length": 32768,
    "top_p": 0.9,
    "repeat_penalty": 1.1,
}


DEFAULT_HISTORY_SETTINGS = {
    "history_enabled": True,
    "max_history_entries": 1000,
}


DEFAULT_DIAGNOSTIC_SETTINGS = {
    "diagnostic_level": "standard",
}


SETUP_MODE_PRESETS = {
    "llama-cpp-direct": {
        "adapter": "LlamaCppAdapter",
        "base_url": "http://127.0.0.1:3000",
        "model": DEFAULT_MODEL,
    },
    "open-webui": {
        "adapter": "OpenWebUIAdapter",
        "base_url": "http://127.0.0.1:8080",
        "model": DEFAULT_MODEL,
    },
    "ollama": {
        "adapter": "OllamaAdapter",
        "base_url": "http://127.0.0.1:11434",
        "model": DEFAULT_MODEL,
    },
    "manual-advanced": {
        "adapter": "Manual",
        "base_url": "",
        "model": DEFAULT_MODEL,
    },
}


def get_llm_defaults() -> dict:
    return deepcopy(DEFAULT_LLM_SETTINGS)


def get_history_defaults() -> dict:
    return deepcopy(DEFAULT_HISTORY_SETTINGS)


def get_diagnostic_defaults() -> dict:
    return deepcopy(DEFAULT_DIAGNOSTIC_SETTINGS)


def get_setup_preset(setup_mode: str) -> dict:
    if setup_mode not in SETUP_MODE_PRESETS:
        raise ValueError(f"Unknown setup mode: {setup_mode}")

    return deepcopy(SETUP_MODE_PRESETS[setup_mode])


def build_default_config(setup_mode: str) -> dict:
    config = {
        "setup_mode": setup_mode,
    }

    config.update(get_setup_preset(setup_mode))
    config.update(get_llm_defaults())
    config.update(get_history_defaults())
    config.update(get_diagnostic_defaults())

    return config
