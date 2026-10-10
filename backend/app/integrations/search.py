from typing import Protocol

from app.schemas.restaurant_search import SearchResult


class SearchProvider(Protocol):
    """Replaceable boundary for web search providers such as Tavily."""

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        """Search for sources; concrete adapters must preserve source metadata."""
        ...
