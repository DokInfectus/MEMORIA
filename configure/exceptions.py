class ConfigureError(Exception):
    """Basisfehler des MEMORIA Configure Moduls."""
    pass


class RuntimeConfigError(ConfigureError):
    """Basisfehler fuer Runtime-Konfiguration."""
    pass


class RuntimeConfigValidationError(RuntimeConfigError):
    """Fehler bei der Validierung der Runtime-Konfiguration."""
    pass


class RuntimeConfigReadError(RuntimeConfigError):
    """Fehler beim Lesen der Runtime-Konfiguration."""
    pass


class RuntimeConfigWriteError(RuntimeConfigError):
    """Fehler beim Schreiben der Runtime-Konfiguration."""
    pass
