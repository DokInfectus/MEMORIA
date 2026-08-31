from configure.profiles import (
    list_profiles,
    describe_profile,
    get_profile_settings,
)


def get_profile_options() -> list:
    return list_profiles()


def get_profile_labels() -> list:
    labels = []

    for profile_name in list_profiles():
        labels.append(describe_profile(profile_name))

    return labels


def build_profile_summary(profile_name: str) -> dict:
    settings = get_profile_settings(profile_name)

    return {
        "profile": profile_name,
        "context_length": settings.get("context_length"),
        "response_tokens": settings.get("max_tokens"),
        "memory_budget": settings.get("memory_token_budget"),
        "history_budget": settings.get("history_token_budget"),
        "reserved_output": settings.get("reserved_output_tokens"),
        "is_custom": not bool(settings),
    }
