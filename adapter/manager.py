from adapter.base import BaseAdapter
from adapter.exceptions import (
    AdapterExecutionError,
    AdapterNotConfiguredError,
)


class AdapterManager:
    """
    Koordiniert den aktiven MEMORIA Adapter.
    """

    def __init__(self):
        self.adapter = None

    def configure(self, adapter: BaseAdapter) -> None:
        """
        Setzt den aktiven Adapter.
        """
        self.adapter = adapter

    def send(self, prompt: str) -> str:
        """
        Übergibt einen fertigen Prompt an den aktiven Adapter.
        """

        if self.adapter is None:
            raise AdapterNotConfiguredError(
                "Kein Adapter wurde konfiguriert."
            )

        try:
            return self.adapter.send(prompt)

        except Exception as e:
            raise AdapterExecutionError(str(e))
