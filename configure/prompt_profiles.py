from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class PromptProfile:
    key: str
    label: str
    description: str


@dataclass(frozen=True)
class PromptProfileDetection:
    model_name: str
    profile: str
    confidence: str
    reason: str


PROMPT_PROFILES: Dict[str, PromptProfile] = {
    "auto": PromptProfile(
        key="auto",
        label="Auto Detect",
        description="Try to detect the prompt profile from the backend model name.",
    ),
    "gemma": PromptProfile(
        key="gemma",
        label="Gemma",
        description="Google Gemma family.",
    ),
    "llama": PromptProfile(
        key="llama",
        label="Llama",
        description="Meta Llama family.",
    ),
    "mistral": PromptProfile(
        key="mistral",
        label="Mistral",
        description="Mistral, Mixtral, Codestral, Devstral style models.",
    ),
    "qwen": PromptProfile(
        key="qwen",
        label="Qwen",
        description="Alibaba Qwen family.",
    ),
    "deepseek": PromptProfile(
        key="deepseek",
        label="DeepSeek",
        description="DeepSeek style models.",
    ),
    "phi": PromptProfile(
        key="phi",
        label="Phi",
        description="Microsoft Phi family.",
    ),
    "chatml": PromptProfile(
        key="chatml",
        label="ChatML",
        description="ChatML-compatible models.",
    ),
    "alpaca": PromptProfile(
        key="alpaca",
        label="Alpaca / Legacy",
        description="Legacy instruction style models.",
    ),
    "generic": PromptProfile(
        key="generic",
        label="Generic",
        description="Safe fallback profile when no specific family is known.",
    ),
    "custom": PromptProfile(
        key="custom",
        label="Custom",
        description="User-defined prompt profile.",
    ),
}


ALIAS_RULES = [
    ("gemma", ["gemma", "shieldgemma", "paligemma"]),
    ("llama", ["llama", "llama2", "llama3", "llama4", "codellama"]),
    ("mistral", ["mistral", "mixtral", "codestral", "devstral", "ministral"]),
    ("qwen", ["qwen", "qwq"]),
    ("deepseek", ["deepseek", "deepseek-r1", "deepseek-v3"]),
    ("phi", ["phi", "phi3", "phi4"]),
    ("chatml", ["chatml"]),
    ("alpaca", ["alpaca", "vicuna", "guanaco"]),
]


def normalize_model_name(model_name: str) -> str:
    value = str(model_name or "").lower().strip()

    for char in ["_", ".", ":", "/", "\\", "(", ")", "[", "]"]:
        value = value.replace(char, "-")

    while "--" in value:
        value = value.replace("--", "-")

    return value


def get_prompt_profile_options() -> List[PromptProfile]:
    return list(PROMPT_PROFILES.values())


def validate_prompt_profile(profile: str) -> str:
    value = str(profile or "").strip().lower()

    if value not in PROMPT_PROFILES:
        raise ValueError(f"Unknown prompt profile: {profile}")

    return value


def detect_prompt_profile(model_name: str) -> PromptProfileDetection:
    normalized = normalize_model_name(model_name)

    if not normalized:
        return PromptProfileDetection(
            model_name=str(model_name or ""),
            profile="custom",
            confidence="none",
            reason="No backend model name was provided.",
        )

    for profile, aliases in ALIAS_RULES:
        for alias in aliases:
            if alias in normalized:
                return PromptProfileDetection(
                    model_name=model_name,
                    profile=profile,
                    confidence="high",
                    reason=f"Matched alias '{alias}' in backend model name.",
                )

    return PromptProfileDetection(
        model_name=model_name,
        profile="custom",
        confidence="none",
        reason="No known prompt profile alias matched.",
    )


def resolve_prompt_profile(
    backend_model_name: str,
    selected_profile: str = "auto",
    custom_profile: Optional[str] = None,
) -> PromptProfileDetection:
    selected = validate_prompt_profile(selected_profile)

    if selected == "auto":
        return detect_prompt_profile(backend_model_name)

    if selected == "custom":
        custom = str(custom_profile or "").strip().lower()

        if not custom:
            return PromptProfileDetection(
                model_name=backend_model_name,
                profile="custom",
                confidence="user-required",
                reason="Custom profile selected but no custom value was provided.",
            )

        return PromptProfileDetection(
            model_name=backend_model_name,
            profile=custom,
            confidence="user-defined",
            reason="User provided a custom prompt profile.",
        )

    return PromptProfileDetection(
        model_name=backend_model_name,
        profile=selected,
        confidence="user-selected",
        reason="User selected the prompt profile manually.",
    )
