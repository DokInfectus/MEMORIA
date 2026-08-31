class FilesystemError(Exception):
    """Basisfehler für alle MEMORIA-Dateisystemfehler."""
    pass


class FileWriteError(FilesystemError):
    """Fehler beim Schreiben einer Datei."""
    pass


class FileReadError(FilesystemError):
    """Fehler beim Lesen einer Datei."""
    pass


class JsonReadError(FilesystemError):
    """Fehler beim Lesen einer JSON-Datei."""
    pass


class JsonWriteError(FilesystemError):
    """Fehler beim Schreiben einer JSON-Datei."""
    pass
