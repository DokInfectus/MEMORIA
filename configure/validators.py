class ValidationError(Exception):
    """Fehler bei einfacher Benutzer-Eingabevalidierung."""
    pass


YES_NO_LIKE_VALUES = {
    "y",
    "yes",
    "j",
    "ja",
    "n",
    "no",
    "nein",
}


def validate_model_name(model: str) -> str:
    value = str(model).strip()

    if not value:
        raise ValidationError("Model name must not be empty.")

    if value.lower() in YES_NO_LIKE_VALUES:
        raise ValidationError(
            "Model name looks like a yes/no answer, not like a model name."
        )

    return value
