import math

from context.builder import ContextBuilder
from context.exceptions import EmptyContextError
from context_engine.exceptions import ContextGenerationError
from configure.manager import ConfigureManager
from profile.manager import ProfileManager
from retrieval.manager import RetrievalManager


DEFAULT_MEMORY_CHARS_PER_TOKEN = 3.0


class ContextEngineManager:
    """
    Koordiniert Profil, Retrieval und Context Builder.
    """

    def __init__(self):
        self.retrieval = RetrievalManager()
        self.builder = ContextBuilder()
        self.profiles = ProfileManager()
        self.configure = ConfigureManager()

    def _runtime_memory_character_budget(self):
        """Translate the configured memory token budget into a local estimate.

        MEMORIA currently has no model tokenizer in the context path.
        The established project estimate is therefore 3 characters/token.
        """

        try:
            runtime = self.configure.load_runtime_config()
            token_budget = int(
                runtime.get("memory_token_budget") or 0
            )
        except Exception:
            return None

        if token_budget <= 0:
            return None

        return int(
            token_budget * DEFAULT_MEMORY_CHARS_PER_TOKEN
        )

    def analyze_memory_token_usage(
        self,
        query: str,
        model: str = "gemma",
        max_entries: int = None,
        max_characters: int = None,
    ) -> dict:
        """Estimate the memory-context cost without exposing its contents."""

        try:
            profile = self.profiles.load(model)

            entries = (
                max_entries
                if max_entries is not None
                else profile.get("max_entries", 5)
            )

            if max_characters is not None:
                characters = max_characters
            else:
                characters = self._runtime_memory_character_budget()

                if characters is None:
                    characters = profile.get(
                        "max_characters",
                        4000,
                    )

            knowledge = self.retrieval.search(query)
            retrieved_entries = len(knowledge)

            try:
                context, stats = self.builder.build_with_stats(
                    knowledge,
                    max_entries=entries,
                    max_characters=characters,
                )

                used_entries = int(
                    stats.get("used_entries", 0)
                )
                estimated_memory_tokens = int(
                    math.ceil(
                        len(context)
                        / DEFAULT_MEMORY_CHARS_PER_TOKEN
                    )
                )

            except EmptyContextError:
                used_entries = 0
                estimated_memory_tokens = 0

            return {
                "retrieved_entries": retrieved_entries,
                "used_entries": used_entries,
                "discarded_entries": max(
                    retrieved_entries - used_entries,
                    0,
                ),
                "estimated_memory_tokens": estimated_memory_tokens,
            }

        except Exception as e:
            raise ContextGenerationError(str(e))

    def generate(
        self,
        query: str,
        model: str = "gemma",
        max_entries: int = None,
        max_characters: int = None,
    ) -> str:

        try:
            profile = self.profiles.load(model)

            entries = (
                max_entries
                if max_entries is not None
                else profile.get("max_entries", 5)
            )

            if max_characters is not None:
                characters = max_characters
            else:
                characters = self._runtime_memory_character_budget()

                if characters is None:
                    characters = profile.get(
                        "max_characters",
                        4000,
                    )

            knowledge = self.retrieval.search(query)

            try:
                return self.builder.build(
                    knowledge,
                    max_entries=entries,
                    max_characters=characters,
                )

            except EmptyContextError:
                return "=== MEMORIA CONTEXT ===\n\nKeine passende Erinnerung gefunden.\n\n======================="

        except Exception as e:
            raise ContextGenerationError(str(e))
