class QueryError(Exception):
    """Basisfehler des MEMORIA Query Extractors."""
    pass


class QueryExtractionError(QueryError):
    """Fehler beim Extrahieren einer Retrieval Query."""
    pass
