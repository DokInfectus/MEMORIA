from dataclasses import dataclass


@dataclass(frozen=True)
class PromptContextMapping:
    prompt_profile: str
    context_profile: str
    reason: str


PROMPT_TO_CONTEXT_PROFILE = {
    "auto": "gemma",
    "gemma": "gemma",
    "llama": "gemma",
    "mistral": "gemma",
    "qwen": "gemma",
    "deepseek": "gemma",
    "phi": "gemma",
    "chatml": "gemma",
    "alpaca": "gemma",
    "generic": "gemma",
    "custom": "gemma",
}


def resolve_context_profile(prompt_profile: str) -> PromptContextMapping:
    normalized = str(prompt_profile or "").strip().lower()

    if not normalized:
        normalized = "generic"

    context_profile = PROMPT_TO_CONTEXT_PROFILE.get(normalized, "gemma")

    if context_profile == normalized:
        reason = "Prompt profile is directly supported as context profile."
    else:
        reason = (
            f"Prompt profile '{normalized}' is mapped to stable context profile "
            f"'{context_profile}' until native context support exists."
        )

    return PromptContextMapping(
        prompt_profile=normalized,
        context_profile=context_profile,
        reason=reason,
    )
