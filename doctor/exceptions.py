class DoctorError(Exception):
    """Basisfehler des MEMORIA Doctor."""
    pass


class DoctorBuildError(DoctorError):
    """Fehler beim Erzeugen des Doctor Reports."""
    pass
