from adapter.base import BaseAdapter


class MockAdapter(BaseAdapter):
    """
    Testadapter für MEMORIA.

    Simuliert ein LLM-Backend,
    ohne eine echte externe Schnittstelle zu verwenden.
    """

    def send(self, prompt: str) -> str:
        return (
            "=== MOCK BACKEND RESPONSE ===\n\n"
            "Prompt wurde erfolgreich empfangen.\n\n"
            f"Prompt Länge: {len(prompt)} Zeichen\n\n"
            "Status: OK"
        )
