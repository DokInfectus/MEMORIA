class PromptEngineError(Exception):
    """Basisfehler der MEMORIA Prompt Engine."""
    pass


class PromptGenerationError(PromptEngineError):
    """Fehler beim Erzeugen eines finalen Prompts."""
    pass
