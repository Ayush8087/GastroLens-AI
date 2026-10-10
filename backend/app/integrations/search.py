from typing import Protocol


class SearchProvider(Protocol):
    """Replaceable boundary for web search providers such as Tavily."""

    async def search(self, query: str) -> list[dict[str, object]]:
        """Search for sources; concrete adapters must preserve source metadata."""
        ...
