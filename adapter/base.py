from abc import ABC, abstractmethod


class BaseAdapter(ABC):
    """
    Basisklasse für alle MEMORIA Adapter.

    Ein Adapter überträgt einen fertigen Prompt
    an ein externes LLM-Backend und gibt die Antwort zurück.
    """

    @abstractmethod
    def send(self, prompt: str) -> str:
        """
        Sendet einen fertigen Prompt an ein Backend
        und gibt die Antwort des Backends zurück.
        """
        pass
