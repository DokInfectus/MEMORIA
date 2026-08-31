class DiagnosticsError(Exception):
    """Basisfehler der MEMORIA Systemdiagnose."""
    pass


class BackendDiagnosticsError(DiagnosticsError):
    """Fehler bei der Backend-Diagnose."""
    pass
