import json
from pathlib import Path

from logger import logger

from filesystem.exceptions import (
    FileReadError,
    FileWriteError,
    JsonReadError,
    JsonWriteError,
)


class FilesystemManager:
    """
    Zentrale Dateischnittstelle von MEMORIA.
    Alle Dateioperationen laufen ausschließlich über diese Klasse.
    """

    def ensure_directory(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)

    def exists(self, filepath: Path) -> bool:
        return filepath.exists()

    def write_text(self, filepath: Path, text: str):
        try:
            self.ensure_directory(filepath.parent)

            with open(filepath, "w", encoding="utf-8") as file:
                file.write(text.rstrip() + "\n")

            logger.info(f"Datei gespeichert: {filepath}")

        except Exception as e:
            raise FileWriteError(str(e))

    def read_text(self, filepath: Path) -> str:
        try:
            with open(filepath, "r", encoding="utf-8") as file:
                return file.read()

        except Exception as e:
            raise FileReadError(str(e))

    def write_json(self, filepath: Path, data: dict):
        try:
            self.ensure_directory(filepath.parent)

            with open(filepath, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)

            logger.info(f"JSON gespeichert: {filepath}")

        except Exception as e:
            raise JsonWriteError(str(e))

    def read_json(self, filepath: Path) -> dict:
        try:
            with open(filepath, "r", encoding="utf-8") as file:
                return json.load(file)

        except Exception as e:
            raise JsonReadError(str(e))
