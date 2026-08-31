class PromptError(Exception):
    """Basisfehler des MEMORIA Prompt Builders."""
    pass


class PromptBuildError(PromptError):
    """Fehler beim Erzeugen eines Prompts."""
    pass
