from typing import Dict, Optional

from history_filter.filter import HistoryFilter
from history_filter.exceptions import HistoryFilterBuildError


class HistoryFilterManager:
    """
    Koordiniert den MEMORIA Conversation History Filter.
    """

    def __init__(self):
        self.filter = HistoryFilter()

    def process(
        self,
        history: str,
        max_entries: Optional[int] = None,
        max_characters: Optional[int] = None,
        include_metadata: bool = True,
    ) -> str:

        try:
            return self.filter.filter_text(
                history,
                max_entries=max_entries,
                max_characters=max_characters,
                include_metadata=include_metadata,
            )

        except Exception as e:
            raise HistoryFilterBuildError(str(e))

    def get_stats(self) -> Dict[str, int]:
        return self.filter.get_stats()
