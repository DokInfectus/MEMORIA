class ContextEngineError(Exception):
    """Basisfehler der MEMORIA Context Engine."""
    pass


class ContextGenerationError(ContextEngineError):
    """Fehler beim Erzeugen eines MEMORIA Contexts."""
    pass
