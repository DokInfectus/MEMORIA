class HistoryFilterError(Exception):
    """Basisfehler des MEMORIA History Filters."""
    pass


class HistoryFilterBuildError(HistoryFilterError):
    """Fehler beim Filtern der Conversation History."""
    pass
