class ContextError(Exception):
    """Basisfehler des MEMORIA Context Builders."""
    pass


class EmptyContextError(ContextError):
    """Es konnten keine Context-Daten erzeugt werden."""
    pass
