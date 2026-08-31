from typing import Any, Dict, List


class FinalValidationResult:
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.info: List[str] = []

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def add_info(self, message: str) -> None:
        self.info.append(message)

    def is_ok(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.is_ok(),
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
        }


def validate_final_configuration(config: Dict[str, Any]) -> FinalValidationResult:
    result = FinalValidationResult()

    required_text_fields = [
        "setup_mode",
        "adapter",
        "base_url",
        "model",
    ]

    for field in required_text_fields:
        value = str(config.get(field, "")).strip()

        if not value:
            result.add_error(f"Missing required field: {field}")

    numeric_fields = [
        "context_length",
        "response_tokens",
        "memory_budget",
        "history_budget",
        "reserved_output",
    ]

    numbers = {}

    for field in numeric_fields:
        try:
            value = int(config.get(field))
            numbers[field] = value
        except Exception:
            result.add_error(f"Invalid numeric field: {field}")
            continue

        if value < 1:
            result.add_error(f"{field} must be greater than 0.")

    if result.errors:
        return result

    context_length = numbers["context_length"]
    memory_budget = numbers["memory_budget"]
    history_budget = numbers["history_budget"]
    reserved_output = numbers["reserved_output"]
    response_tokens = numbers["response_tokens"]

    used_context = memory_budget + history_budget + reserved_output

    if used_context > context_length:
        result.add_error(
            "Memory Budget + History Budget + Reserved Output "
            "exceeds Context Length."
        )

    if response_tokens > reserved_output:
        result.add_warning(
            "Response Tokens is greater than Reserved Output. "
            "The model may not have enough reserved answer space."
        )

    if response_tokens > context_length:
        result.add_error(
            "Response Tokens must not be greater than Context Length."
        )

    remaining_context = context_length - used_context

    result.add_info(f"Context Length: {context_length}")
    result.add_info(f"Used Context Budget: {used_context}")
    result.add_info(f"Remaining Context Budget: {remaining_context}")

    if remaining_context < 512:
        result.add_warning(
            "Remaining Context Budget is very small. "
            "Prompt overhead may become a problem."
        )

    return result
