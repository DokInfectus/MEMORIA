class RetrievalError(Exception):
    """Basisfehler der MEMORIA Retrieval Engine."""
    pass


class KnowledgeNotFoundError(RetrievalError):
    """Keine passende Knowledge gefunden."""
    pass


class RetrievalLoadError(RetrievalError):
    """Fehler beim Laden einer Knowledge-Datei."""
    pass
