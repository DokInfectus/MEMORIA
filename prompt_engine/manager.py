from typing import Dict

from history.manager import HistoryManager
from history_filter.manager import HistoryFilterManager
from query.manager import QueryManager
from context_engine.manager import ContextEngineManager
from prompt.builder import PromptBuilder
from prompt_engine.exceptions import PromptGenerationError


class PromptEngineManager:
    """
    Koordiniert den vollständigen Prompt-Aufbau von MEMORIA.
    """

    def __init__(self):
        self.history = HistoryManager()
        self.history_filter = HistoryFilterManager()
        self.query_manager = QueryManager()
        self.context_engine = ContextEngineManager()
        self.builder = PromptBuilder()

        self.history_filter_stats: Dict[str, int] = {}
        self.retrieval_query: str = ""

    def generate(
        self,
        user_prompt: str,
        model: str = "gemma",
        system_prompt: str = "Du bist MEMORIA.",
        max_history_entries: int = 3,
        max_history_characters: int = 4000,
        include_history_metadata: bool = False,
    ) -> str:

        try:
            history = self.history.build_context()

            history = self.history_filter.process(
                history,
                max_entries=max_history_entries,
                max_characters=max_history_characters,
                include_metadata=include_history_metadata,
            )

            self.history_filter_stats = self.history_filter.get_stats()

            self.retrieval_query = self.query_manager.build_query(user_prompt)

            context = self.context_engine.generate(
                query=self.retrieval_query,
                model=model,
            )

            return self.builder.build(
                system_prompt=system_prompt,
                history=history,
                context=context,
                user_prompt=user_prompt,
            )

        except Exception as e:
            raise PromptGenerationError(str(e))

    def get_history_filter_stats(self) -> Dict[str, int]:
        return dict(self.history_filter_stats)

    def get_retrieval_query(self) -> str:
        return self.retrieval_query
