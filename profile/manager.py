import json

from config import BASE_DIR
from profile.exceptions import (
    ProfileLoadError,
    ProfileNotFoundError,
)


class ProfileManager:
    """
    Lädt MEMORIA Modellprofile.
    """

    def __init__(self):
        self.profile_dir = BASE_DIR / "config" / "context" / "profiles"

    def load(self, model: str) -> dict:

        profile_file = self.profile_dir / f"{model.lower()}.json"

        if not profile_file.exists():
            raise ProfileNotFoundError(
                f"Profil '{model}' wurde nicht gefunden."
            )

        try:
            with open(profile_file, "r", encoding="utf-8") as f:
                return json.load(f)

        except Exception as e:
            raise ProfileLoadError(str(e))
