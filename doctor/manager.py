from diagnostics.manager import DiagnosticsManager
from doctor.builder import DoctorReportBuilder
from doctor.exceptions import DoctorError


class DoctorManager:
    """
    Koordiniert den MEMORIA Doctor.
    """

    def __init__(self):
        self.diagnostics = DiagnosticsManager()
        self.builder = DoctorReportBuilder()

    def run_report(self) -> str:
        try:
            diagnostics_result = self.diagnostics.run()
            return self.builder.build(diagnostics_result)

        except Exception as e:
            raise DoctorError(str(e))
