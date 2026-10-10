import asyncio
import logging

import httpx
from pydantic import SecretStr, ValidationError

from app.integrations.search import SearchProvider
from app.schemas.restaurant_search import SearchResult

logger = logging.getLogger(__name__)


class SearchProviderError(Exception):
    """A provider failure safe to report without exposing credentials or raw responses."""


class TavilySearchProvider(SearchProvider):
    endpoint = "https://api.tavily.com/search"

    def __init__(
        self,
        api_key: SecretStr | None,
        *,
        client: httpx.AsyncClient | None = None,
        attempts: int = 3,
        retry_delay: float = 0.15,
    ) -> None:
        self.api_key = api_key
        self.client = client
        self.attempts = max(1, min(attempts, 3))
        self.retry_delay = max(0.0, min(retry_delay, 1.0))

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if self.api_key is None or not self.api_key.get_secret_value().strip():
            raise SearchProviderError(
                "Tavily search is not configured (TAVILY_API_KEY is missing)."
            )
        payload = {
            "api_key": self.api_key.get_secret_value(),
            "query": query,
            "search_depth": "basic",
            "max_results": max(1, min(max_results, 10)),
            "include_answer": False,
            "include_raw_content": False,
        }
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(
            timeout=httpx.Timeout(12.0), follow_redirects=False
        )
        try:
            for attempt in range(self.attempts):
                try:
                    response = await client.post(self.endpoint, json=payload)
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt + 1 < self.attempts:
                            await asyncio.sleep(self.retry_delay * (2**attempt))
                            continue
                        raise SearchProviderError("Tavily search is temporarily unavailable.")
                    response.raise_for_status()
                    data = response.json()
                    raw_results = data.get("results") if isinstance(data, dict) else None
                    if not isinstance(raw_results, list):
                        raise SearchProviderError("Tavily returned a malformed search response.")
                    results: list[SearchResult] = []
                    for raw in raw_results:
                        if not isinstance(raw, dict) or not isinstance(raw.get("url"), str):
                            continue
                        try:
                            results.append(
                                SearchResult(
                                    url=raw["url"],
                                    title=raw.get("title")
                                    if isinstance(raw.get("title"), str)
                                    else "",
                                    snippet=raw.get("content")
                                    if isinstance(raw.get("content"), str)
                                    else "",
                                )
                            )
                        except ValidationError:
                            continue
                    if raw_results and not results:
                        raise SearchProviderError("Tavily returned malformed search results.")
                    return results
                except httpx.TransportError as exc:
                    if attempt + 1 == self.attempts:
                        logger.warning(
                            "tavily_transport_failure", extra={"error_type": type(exc).__name__}
                        )
                        raise SearchProviderError(
                            "Tavily search is temporarily unavailable."
                        ) from exc
                    await asyncio.sleep(self.retry_delay * (2**attempt))
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code in (401, 403):
                        raise SearchProviderError(
                            "Tavily rejected the configured credentials."
                        ) from exc
                    raise SearchProviderError("Tavily search request failed.") from exc
                except ValueError as exc:
                    raise SearchProviderError("Tavily returned invalid JSON.") from exc
            raise SearchProviderError("Tavily search is temporarily unavailable.")
        finally:
            if owns_client:
                await client.aclose()
