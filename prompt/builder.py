from prompt.exceptions import PromptBuildError


class PromptBuilder:
    """
    Erstellt den finalen Prompt für ein LLM.
    """

    def build(
        self,
        system_prompt: str,
        context: str,
        user_prompt: str,
        history: str = "",
    ) -> str:

        try:

            return f"""=== SYSTEM ===

{system_prompt}

====================

{history}

====================

{context}

====================

=== USER ===

{user_prompt}
"""

        except Exception as e:
            raise PromptBuildError(str(e))
