from configure.profile_selection import (
    get_profile_options,
    get_profile_labels,
    build_profile_summary,
)
from ui.terminal.prompt import ask_choice, ask_text
from ui.terminal.screen import section, status, note


def ask_int_value(label: str, default: int) -> int:
    while True:
        value = ask_text(label, str(default))

        try:
            number = int(value)
        except ValueError:
            status(label, "Please enter a valid number.", ok=False)
            continue

        if number < 1:
            status(label, "Value must be greater than 0.", ok=False)
            continue

        return number


def ask_custom_profile_values() -> dict:
    section("Custom Token Budgets")

    note("Enter your own values.")
    note("Press Enter to keep the suggested default.")

    return {
        "profile": "custom",
        "context_length": ask_int_value("Context Length", 32768),
        "response_tokens": ask_int_value("Response Tokens", 2048),
        "memory_budget": ask_int_value("Memory Budget", 4096),
        "history_budget": ask_int_value("History Budget", 2048),
        "reserved_output": ask_int_value("Reserved Output", 2048),
        "is_custom": True,
    }


def show_profile_summary(summary: dict) -> None:
    section("Selected Profile")

    status("Profile", summary["profile"], ok=True)
    status("Context Length", str(summary["context_length"]), ok=None)
    status("Response Tokens", str(summary["response_tokens"]), ok=None)
    status("Memory Budget", str(summary["memory_budget"]), ok=None)
    status("History Budget", str(summary["history_budget"]), ok=None)
    status("Reserved Output", str(summary["reserved_output"]), ok=None)


def ask_profile_selection() -> dict:
    section("Choose Configuration Profile")

    options = get_profile_options()
    labels = get_profile_labels()

    choice = ask_choice(
        "Available profiles",
        labels,
        default=1,
    )

    profile_name = options[choice - 1]

    if profile_name == "custom":
        summary = ask_custom_profile_values()
    else:
        summary = build_profile_summary(profile_name)

    show_profile_summary(summary)

    return summary
