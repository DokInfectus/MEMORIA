class ProfileError(Exception):
    """Basisfehler des MEMORIA Profile Managers."""
    pass


class ProfileLoadError(ProfileError):
    """Fehler beim Laden eines Modellprofils."""
    pass


class ProfileNotFoundError(ProfileError):
    """Modellprofil wurde nicht gefunden."""
    pass
