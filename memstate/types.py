from typing import Any, Protocol

from memstate.schemas import Fact, Operation, SearchResult


class MemoryHook(Protocol):
    """
    Defines the MemoryHook protocol, which provides a callable interface
    for operations involving facts and identifiers.

    This protocol is intended for usage in scenarios where operations
    must be performed with specific facts and their associated identifiers.
    It ensures that any implementing object adheres to the defined call signature.
    """

    def __call__(self, op: Operation, fact_id: str, fact: Fact | None) -> None:
        """
        Executes the instance as a callable. The method processes an operation with an
        associated fact ID and optional fact data.

        Args:
            op (Operation): Operation to be processed.
            fact_id (str): Identifier associated with the fact.
            fact (Fact | None): Optional fact data related to the operation.

        Returns:
            None
        """
        ...

    def search(
        self, query: str, limit: int = 5, filters: dict[str, Any] | None = None, score_threshold: float | None = None
    ) -> list[SearchResult]:
        """
        Searches for results based on a query string, a specified limit, and optional filters.

        This function performs a search and returns a list of results
        matching the input query. The number of results returned can
        be limited by the `limit` parameter. Filters can also be applied
        to refine the search. If no filters are provided, the search is
        performed without additional constraints.

        Args:
            query (str): A string representing the search query.
            limit (int): An integer specifying the maximum number of results to return. Defaults to 5.
            filters (dict[str, Any] | None): A dictionary containing optional filtering conditions
                for the search. Each key-value pair represents a filter rule
                to apply. If `None`, no filters are applied.
            score_threshold (float | None): Optional threshold value for the search score.
        Returns:
            A list of `SearchResult` objects corresponding to the
                matches found according to the query, limit, and filters.
        """
        ...


class AsyncMemoryHook(Protocol):
    """
    Defines the AsyncMemoryHook protocol, which provides a callable interface
    for operations involving facts and identifiers.

    This protocol is intended for usage in scenarios where operations
    must be performed with specific facts and their associated identifiers.
    It ensures that any implementing object adheres to the defined call signature.
    """

    async def __call__(self, op: Operation, fact_id: str, fact: Fact | None) -> None:
        """
        Asynchronously executes the instance as a callable. The method processes an operation with an
        associated fact ID and optional fact data.

        Args:
            op (Operation): Operation to be processed.
            fact_id (str): Identifier associated with the fact.
            fact (Fact | None): Optional fact data related to the operation.

        Returns:
            None
        """
        ...

    async def search(
        self, query: str, limit: int = 5, filters: dict[str, Any] | None = None, score_threshold: float | None = None
    ) -> list[SearchResult]:
        """
        Asynchronously searches for results based on a query string, a specified limit, and optional filters.

        This function performs a search and returns a list of results
        matching the input query. The number of results returned can
        be limited by the `limit` parameter. Filters can also be applied
        to refine the search. If no filters are provided, the search is
        performed without additional constraints.

        Args:
            query (str): A string representing the search query.
            limit (int): An integer specifying the maximum number of results to return. Defaults to 5.
            filters (dict[str, Any] | None): A dictionary containing optional filtering conditions
                for the search. Each key-value pair represents a filter rule
                to apply. If `None`, no filters are applied.
            score_threshold (float | None): Optional threshold value for the search score.
        Returns:
            A list of `SearchResult` objects corresponding to the
                matches found according to the query, limit, and filters.
        """
        ...
