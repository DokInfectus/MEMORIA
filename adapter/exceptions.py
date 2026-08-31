class AdapterError(Exception):
    """Basisfehler des MEMORIA Adapter Layers."""
    pass


class AdapterNotConfiguredError(AdapterError):
    """Kein Adapter wurde konfiguriert."""
    pass


class AdapterExecutionError(AdapterError):
    """Fehler beim Ausführen eines Adapters."""
    pass
