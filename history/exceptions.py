class HistoryError(Exception):
    """Basisfehler der MEMORIA Conversation History."""
    pass


class HistoryLoadError(HistoryError):
    """Fehler beim Laden der Conversation History."""
    pass


class HistoryBuildError(HistoryError):
    """Fehler beim Erzeugen eines History-Kontexts."""
    pass
