from typing import Any, Dict, List

from doctor.exceptions import DoctorBuildError


class DoctorReportBuilder:
    """
    Erzeugt einen menschenlesbaren MEMORIA Doctor Report.

    Der Report enthält nur technische Diagnoseinformationen.
    Keine privaten Chats.
    Keine Tokens.
    Keine Personas.
    Keine vollständigen Prompts.
    """

    def build(self, diagnostics: Dict[str, Any]) -> str:
        try:
            backends = diagnostics.get("backends", {})

            lines: List[str] = [
                "=== MEMORIA DOCTOR REPORT ===",
                "",
                "Backends",
                "--------",
            ]

            self._add_llama_cpp(lines, backends.get("llama_cpp", []))
            self._add_open_webui(lines, backends.get("open_webui", []))
            self._add_ollama(lines, backends.get("ollama", []))

            lines.extend(
                [
                    "",
                    "Empfehlung",
                    "----------",
                    self._build_recommendation(backends),
                    "",
                    "Datenschutz",
                    "-----------",
                    "- Keine privaten Chats gelesen",
                    "- Keine Tokens ausgegeben",
                    "- Keine Personas ausgegeben",
                    "- Keine Konfiguration veraendert",
                    "",
                    "Status",
                    "------",
                    self._build_status(backends),
                ]
            )

            return "\n".join(lines)

        except Exception as e:
            raise DoctorBuildError(str(e))

    def _add_llama_cpp(
        self,
        lines: List[str],
        entries: List[Dict[str, Any]],
    ) -> None:

        if not entries:
            lines.append("- llama.cpp: nicht gefunden")
            return

        for entry in entries:
            lines.append(
                f"- llama.cpp: gefunden auf {entry.get('base_url')}"
            )
            lines.append(
                f"  OpenAI kompatibel: {entry.get('openai_compatible')}"
            )
            lines.append(
                f"  Empfohlener Adapter: {entry.get('recommended_adapter')}"
            )

    def _add_open_webui(
        self,
        lines: List[str],
        entries: List[Dict[str, Any]],
    ) -> None:

        if not entries:
            lines.append("- Open WebUI: nicht gefunden")
            return

        for entry in entries:
            lines.append(
                f"- Open WebUI: gefunden auf {entry.get('base_url')}"
            )
            lines.append(
                f"  Auth erforderlich: {entry.get('auth_required')}"
            )
            lines.append(
                f"  Adapter: {entry.get('recommended_adapter')}"
            )

    def _add_ollama(
        self,
        lines: List[str],
        entries: List[Dict[str, Any]],
    ) -> None:

        if not entries:
            lines.append("- Ollama: nicht gefunden")
            return

        for entry in entries:
            lines.append(
                f"- Ollama: gefunden auf {entry.get('base_url')}"
            )
            lines.append(
                f"  Empfohlener Adapter: {entry.get('recommended_adapter')}"
            )

    def _build_recommendation(self, backends: Dict[str, Any]) -> str:
        llama_cpp = backends.get("llama_cpp", [])

        if llama_cpp:
            first = llama_cpp[0]
            adapter = first.get("recommended_adapter", "LlamaCppAdapter")
            base_url = first.get("base_url")

            return (
                f"{adapter} verwenden "
                f"mit Backend {base_url}."
            )

        ollama = backends.get("ollama", [])

        if ollama:
            first = ollama[0]
            return (
                f"OllamaAdapter verwenden "
                f"mit Backend {first.get('base_url')}."
            )

        open_webui = backends.get("open_webui", [])

        if open_webui:
            first = open_webui[0]

            if first.get("auth_required"):
                return (
                    "Open WebUI wurde gefunden, benoetigt aber Auth. "
                    "Fuer direkte Tests wird ein Backend-Adapter empfohlen."
                )

            return "OpenWebUIAdapter kann spaeter verwendet werden."

        return (
            "Kein lokales Backend gefunden. "
            "Bitte llama.cpp, Open WebUI oder Ollama starten."
        )

    def _build_status(self, backends: Dict[str, Any]) -> str:
        if backends.get("llama_cpp"):
            return "READY FOR LLAMA.CPP TEST"

        if backends.get("ollama"):
            return "READY FOR OLLAMA TEST"

        if backends.get("open_webui"):
            return "OPEN WEBUI FOUND - AUTH OR ADAPTER SETUP REQUIRED"

        return "NO BACKEND FOUND"
