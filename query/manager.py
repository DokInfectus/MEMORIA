from query.extractor import QueryExtractor
from query.exceptions import QueryExtractionError


class QueryManager:
    """
    Koordiniert die Extraktion einer Retrieval Query.
    """

    def __init__(self):
        self.extractor = QueryExtractor()

    def build_query(self, user_prompt: str) -> str:
        """
        Erzeugt aus einem User Prompt eine Retrieval Query.
        """

        try:
            return self.extractor.extract(user_prompt)

        except Exception as e:
            raise QueryExtractionError(str(e))
