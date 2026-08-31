from dataclasses import dataclass
import re
from typing import Dict, List

from configure.prompt_context_mapping import resolve_context_profile
from configure.prompt_profiles import detect_prompt_profile, normalize_model_name


@dataclass(frozen=True)
class ModelFamily:
    key: str
    label: str
    prompt_profile: str
    description: str


@dataclass(frozen=True)
class ModelSelection:
    model_name: str
    normalized_model_name: str
    family: str
    family_label: str
    prompt_profile: str
    context_profile: str
    model_version: str
    model_size: str
    model_traits: List[str]
    confidence: str
    reason: str
    context_reason: str
    user_confirmation_required: bool = True


MODEL_FAMILIES: Dict[str, ModelFamily] = {
    "gemma": ModelFamily(
        key="gemma",
        label="Gemma",
        prompt_profile="gemma",
        description="Google Gemma style model family.",
    ),
    "llama": ModelFamily(
        key="llama",
        label="Llama",
        prompt_profile="llama",
        description="Meta Llama style model family.",
    ),
    "mistral": ModelFamily(
        key="mistral",
        label="Mistral",
        prompt_profile="mistral",
        description="Mistral, Mixtral, Codestral, Devstral or Ministral style model family.",
    ),
    "qwen": ModelFamily(
        key="qwen",
        label="Qwen",
        prompt_profile="qwen",
        description="Alibaba Qwen style model family.",
    ),
    "deepseek": ModelFamily(
        key="deepseek",
        label="DeepSeek",
        prompt_profile="deepseek",
        description="DeepSeek style model family.",
    ),
    "phi": ModelFamily(
        key="phi",
        label="Phi",
        prompt_profile="phi",
        description="Microsoft Phi style model family.",
    ),
    "chatml": ModelFamily(
        key="chatml",
        label="ChatML",
        prompt_profile="chatml",
        description="ChatML-compatible model family.",
    ),
    "alpaca": ModelFamily(
        key="alpaca",
        label="Alpaca / Legacy",
        prompt_profile="alpaca",
        description="Legacy Alpaca/Vicuna/Guanaco style instruction model family.",
    ),
    "unknown": ModelFamily(
        key="unknown",
        label="Unknown",
        prompt_profile="generic",
        description="Unknown model family. Generic prompt profile is the safe fallback.",
    ),
}


def get_model_families() -> List[ModelFamily]:
    return list(MODEL_FAMILIES.values())



def extract_model_version(normalized_model_name: str, family: str) -> str:
    value = str(normalized_model_name or "")

    if not family or family == "unknown":
        return ""

    # gemma-3-27b-it-q8 -> version 3, size 27B
    match = re.search(rf"{family}-(\d+)-\d+(?:b|m)\b", value)
    if match:
        return match.group(1)

    # llama-3-3-70b-instruct -> version 3.3
    match = re.search(rf"{family}-(\d+)-(\d+)-\d+(?:b|m)\b", value)
    if match:
        return f"{match.group(1)}.{match.group(2)}"

    # qwen2-5-coder-32b -> version 2.5
    match = re.search(rf"{family}(\d+)-(\d+)", value)
    if match:
        return f"{match.group(1)}.{match.group(2)}"

    # llama-3-3-instruct -> version 3.3
    match = re.search(rf"{family}-(\d+)-(\d+)", value)
    if match:
        return f"{match.group(1)}.{match.group(2)}"

    # gemma-3-it / phi-4-mini -> version 3 / 4
    match = re.search(rf"{family}-(\d+)", value)
    if match:
        return match.group(1)

    # qwen3 / llama3
    match = re.search(rf"{family}(\d+)", value)
    if match:
        return match.group(1)

    return ""



def extract_model_size(normalized_model_name: str) -> str:
    value = str(normalized_model_name or "")
    tokens = [token for token in value.split("-") if token]

    for token in tokens:
        match = re.fullmatch(r"(\d+)(b|m)", token)
        if match:
            return f"{match.group(1)}{match.group(2).upper()}"

    return ""


def extract_model_traits(normalized_model_name: str) -> List[str]:
    value = str(normalized_model_name or "")
    traits: List[str] = []

    rules = [
        ("instruct", ["instruct", "it"]),
        ("coder", ["coder", "code", "codestral", "codellama"]),
        ("reasoning", ["reasoning", "r1", "qwq"]),
        ("vision", ["vision", "vl", "paligemma"]),
        ("distill", ["distill"]),
        ("chat", ["chat"]),
        ("gguf", ["gguf"]),
        ("quantized", ["q4", "q5", "q6", "q8", "iq4", "iq5"]),
    ]

    for trait, aliases in rules:
        for alias in aliases:
            if alias in value and trait not in traits:
                traits.append(trait)
                break

    return traits


def select_model_profile(model_name: str) -> ModelSelection:
    normalized = normalize_model_name(model_name)
    detected = detect_prompt_profile(model_name)

    if detected.profile in MODEL_FAMILIES:
        family = MODEL_FAMILIES[detected.profile]
        prompt_profile = family.prompt_profile
        confidence = detected.confidence
        reason = detected.reason
    else:
        family = MODEL_FAMILIES["unknown"]
        prompt_profile = family.prompt_profile
        confidence = "none"
        reason = (
            "No known model family alias matched. "
            "Generic prompt profile is suggested until the user selects a better profile."
        )

    context = resolve_context_profile(prompt_profile)
    model_version = extract_model_version(normalized, family.key)
    model_size = extract_model_size(normalized)
    model_traits = extract_model_traits(normalized)

    return ModelSelection(
        model_name=str(model_name or ""),
        normalized_model_name=normalized,
        family=family.key,
        family_label=family.label,
        prompt_profile=prompt_profile,
        context_profile=context.context_profile,
        model_version=model_version,
        model_size=model_size,
        model_traits=model_traits,
        confidence=confidence,
        reason=reason,
        context_reason=context.reason,
        user_confirmation_required=True,
    )


def format_model_selection(selection: ModelSelection) -> str:
    lines = [
        "MEMORIA LLM MODEL SELECTION V0.2",
        "-" * 60,
        f"Model: {selection.model_name or '(empty)'}",
        f"Normalized: {selection.normalized_model_name or '(empty)'}",
        f"Family: {selection.family} ({selection.family_label})",
        f"Prompt Profile: {selection.prompt_profile}",
        f"Context Profile: {selection.context_profile}",
        f"Model Version: {selection.model_version or 'unknown'}",
        f"Model Size: {selection.model_size or 'unknown'}",
        f"Model Traits: {', '.join(selection.model_traits) if selection.model_traits else 'none'}",
        f"Confidence: {selection.confidence}",
        f"Reason: {selection.reason}",
        f"Context Reason: {selection.context_reason}",
        "",
        "Decision:",
        "MEMORIA suggests this selection, but does not apply it automatically.",
        "The user must confirm before configuration is changed.",
    ]

    return "\n".join(lines)
