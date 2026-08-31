from typing import Any, Dict

from diagnostics.backend import BackendDiagnostics
from diagnostics.exceptions import DiagnosticsError


class DiagnosticsManager:
    """
    Koordiniert die MEMORIA Systemdiagnose.
    """

    def __init__(self):
        self.backend_diagnostics = BackendDiagnostics()

    def run(self) -> Dict[str, Any]:
        """
        Führt alle verfügbaren Diagnosen aus.
        """

        try:
            return {
                "backends": self.backend_diagnostics.run(),
            }

        except Exception as e:
            raise DiagnosticsError(str(e))
