from copy import deepcopy


PROFILE_BALANCED = "balanced"
PROFILE_FAST = "fast-low-context"
PROFILE_MEMORY_HEAVY = "memory-heavy"
PROFILE_LOW_VRAM = "low-vram"
PROFILE_CUSTOM = "custom"


CONFIGURATION_PROFILES = {
    PROFILE_BALANCED: {
        "label": "Balanced",
        "description": "Good default for normal local LLM usage.",
        "settings": {
            "context_length": 32768,
            "max_tokens": 2048,
            "memory_token_budget": 4096,
            "history_token_budget": 2048,
            "reserved_output_tokens": 2048,
        },
    },
    PROFILE_FAST: {
        "label": "Fast / Low Context",
        "description": "Faster responses with smaller memory and history budgets.",
        "settings": {
            "context_length": 8192,
            "max_tokens": 1024,
            "memory_token_budget": 1024,
            "history_token_budget": 512,
            "reserved_output_tokens": 1024,
        },
    },
    PROFILE_MEMORY_HEAVY: {
        "label": "Memory Heavy",
        "description": "More room for memories, knowledge and conversation history.",
        "settings": {
            "context_length": 32768,
            "max_tokens": 2048,
            "memory_token_budget": 8192,
            "history_token_budget": 4096,
            "reserved_output_tokens": 2048,
        },
    },
    PROFILE_LOW_VRAM: {
        "label": "Low VRAM",
        "description": "Conservative settings for weaker hardware.",
        "settings": {
            "context_length": 4096,
            "max_tokens": 512,
            "memory_token_budget": 512,
            "history_token_budget": 256,
            "reserved_output_tokens": 512,
        },
    },
    PROFILE_CUSTOM: {
        "label": "Custom",
        "description": "User controls all token budgets manually.",
        "settings": {},
    },
}


def list_profiles() -> list:
    return list(CONFIGURATION_PROFILES.keys())


def get_profile(profile_name: str) -> dict:
    if profile_name not in CONFIGURATION_PROFILES:
        raise ValueError(f"Unknown configuration profile: {profile_name}")

    return deepcopy(CONFIGURATION_PROFILES[profile_name])


def get_profile_settings(profile_name: str) -> dict:
    profile = get_profile(profile_name)
    return deepcopy(profile["settings"])


def describe_profile(profile_name: str) -> str:
    profile = get_profile(profile_name)

    return (
        f"{profile['label']}: "
        f"{profile['description']}"
    )


def is_custom_profile(profile_name: str) -> bool:
    return profile_name == PROFILE_CUSTOM
