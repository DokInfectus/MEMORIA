from configure.prompt_profiles import (
    get_prompt_profile_options,
    resolve_prompt_profile,
)


def ask_text(prompt: str, default: str = "") -> str:
    if default:
        value = input(f"{prompt} [{default}]: ").strip()
        return value or default

    return input(f"{prompt}: ").strip()


def ask_number(prompt: str, default: int, minimum: int, maximum: int) -> int:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()

        if not raw:
            return default

        try:
            value = int(raw)
        except ValueError:
            print("Please enter a number.")
            continue

        if value < minimum or value > maximum:
            print(f"Please enter a number between {minimum} and {maximum}.")
            continue

        return value


def ask_prompt_profile(backend_model_name: str) -> dict:
    detection = resolve_prompt_profile(
        backend_model_name=backend_model_name,
        selected_profile="auto",
    )

    print()
    print("## Prompt Profile")
    print("----------------------------------------")
    print(f"Backend Model: {backend_model_name}")

    if detection.profile == "custom":
        print("Detected Prompt Profile: custom")
        print("Reason: No known prompt profile alias matched.")
    else:
        print(f"Detected Prompt Profile: {detection.profile}")
        print(f"Reason: {detection.reason}")

    print()
    print("Available prompt profiles")

    options = get_prompt_profile_options()

    for index, profile in enumerate(options, start=1):
        print(f"{index}) {profile.key}: {profile.description}")

    default_index = 1

    if detection.profile != "custom":
        for index, profile in enumerate(options, start=1):
            if profile.key == detection.profile:
                default_index = index
                break

    selected_index = ask_number(
        "Select prompt profile",
        default=default_index,
        minimum=1,
        maximum=len(options),
    )

    selected_profile = options[selected_index - 1].key
    custom_profile = None

    if selected_profile == "custom":
        custom_profile = ask_text(
            "Enter custom prompt profile",
            default="generic",
        )

    resolved = resolve_prompt_profile(
        backend_model_name=backend_model_name,
        selected_profile=selected_profile,
        custom_profile=custom_profile,
    )

    print()
    print("## Selected Prompt Profile")
    print("----------------------------------------")
    print(f"Prompt Profile: {resolved.profile}")
    print(f"Confidence: {resolved.confidence}")
    print(f"Reason: {resolved.reason}")

    return {
        "backend_model": backend_model_name,
        "selected_profile": selected_profile,
        "prompt_profile": resolved.profile,
        "confidence": resolved.confidence,
        "reason": resolved.reason,
    }
