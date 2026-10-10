from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.core.config import Settings, get_settings
from app.integrations.tavily_search import SearchProviderError, TavilySearchProvider
from app.main import app
from app.schemas.restaurant_search import (
    RestaurantCandidate,
    RestaurantSearchRequest,
    SearchResult,
    SourceEvidence,
)
from app.services.restaurant_discovery import RestaurantDiscoveryService, _candidates_from_results
from app.services.source_verification import SourceVerifier, normalize_url


class StaticProvider:
    def __init__(
        self, results: list[SearchResult] | None = None, error: Exception | None = None
    ) -> None:
        self.results = results or []
        self.error = error
        self.queries: list[str] = []

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.results


async def allow_url(_: str) -> bool:
    return True


async def allow_restaurant_host(url: str) -> bool:
    return httpx.URL(url).host == "greenfork.example"


def _candidate(url: str, *, name: str | None = "Green Fork") -> RestaurantCandidate:
    return RestaurantCandidate(
        restaurant_name=name,
        source_evidence=[SourceEvidence(url=url, retrieved_at=datetime.now(UTC))],
        retrieved_at=datetime.now(UTC),
    )


def test_request_preferences_are_validated_and_default_to_barcelona_vegetarian() -> None:
    request = RestaurantSearchRequest(meal="lunch")
    assert request.city == "Barcelona"
    assert request.dietary_requirements == ["vegetarian"]
    assert request.currency == "EUR"

    with pytest.raises(ValidationError):
        RestaurantSearchRequest(meal="brunch")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        RestaurantSearchRequest(meal="dinner", max_results=21)


def test_candidates_deduplicate_normalized_urls_but_keep_other_branches() -> None:
    candidates = _candidates_from_results(
        [
            SearchResult(url="HTTPS://greenfork.example/menu#lunch", title="Green Fork Menu"),
            SearchResult(url="https://greenfork.example/menu", title="Green Fork Menu"),
            SearchResult(
                url="https://greenfork.example/other-branch", title="Green Fork Barcelona"
            ),
        ]
    )
    assert len(candidates) == 2
    assert candidates[0].menu_url == "https://greenfork.example/menu"
    assert candidates[0].dietary_suitability == "unconfirmed"


def test_candidate_keeps_missing_optional_fields_unknown() -> None:
    candidate = _candidates_from_results([SearchResult(url="https://example.org/page")])[0]
    assert candidate.restaurant_name is None
    assert candidate.city_or_address is None
    assert candidate.official_website_url is None
    assert candidate.menu_url is None
    assert "city_or_address" in candidate.unknown_fields


def test_invalid_urls_are_rejected_for_candidate_and_normalizer() -> None:
    assert normalize_url("javascript:alert(1)") is None
    assert normalize_url("https://user:password@example.com") is None
    assert _candidates_from_results([SearchResult(url="file:///etc/passwd")]) == []


@pytest.mark.anyio
async def test_missing_tavily_key_returns_a_clear_provider_error() -> None:
    provider = TavilySearchProvider(None)
    with pytest.raises(SearchProviderError, match="TAVILY_API_KEY"):
        await provider.search("vegetarian lunch Barcelona")


@pytest.mark.anyio
async def test_tavily_malformed_response_is_reported_without_fake_results() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answer": "not a result list"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = TavilySearchProvider(SecretStr("test-key"), client=client, attempts=1)
        with pytest.raises(SearchProviderError, match="malformed"):
            await provider.search("vegetarian lunch Barcelona")


@pytest.mark.anyio
async def test_tavily_rate_limit_uses_bounded_retries() -> None:
    request_count = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(429)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = TavilySearchProvider(
            SecretStr("test-key"), client=client, attempts=10, retry_delay=0
        )
        with pytest.raises(SearchProviderError, match="temporarily unavailable"):
            await provider.search("vegetarian lunch Barcelona")
    assert request_count == 3


@pytest.mark.anyio
async def test_provider_outage_returns_empty_results_and_warning() -> None:
    service = RestaurantDiscoveryService(
        StaticProvider(error=SearchProviderError("provider unavailable")),
        SourceVerifier(safety_check=allow_url),
    )
    result = await service.discover(RestaurantSearchRequest(meal="lunch"))
    assert result.restaurants == []
    assert result.warnings == ["provider unavailable"]


@pytest.mark.anyio
async def test_successful_discovery_queries_multiple_sources_and_deduplicates() -> None:
    provider = StaticProvider(
        [SearchResult(url="https://greenfork.example/menu", title="Green Fork Menu")]
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Green Fork is open for lunch")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = RestaurantDiscoveryService(
            provider, SourceVerifier(client, safety_check=allow_url)
        )
        result = await service.discover(RestaurantSearchRequest(meal="lunch"))

    assert len(provider.queries) == 3
    assert len(result.restaurants) == 1
    assert result.restaurants[0].menu_url == "https://greenfork.example/menu"
    assert result.restaurants[0].verification_status == "verified"
    assert result.restaurants[0].dietary_suitability == "unconfirmed"


@pytest.mark.anyio
async def test_verification_failure_does_not_claim_accessibility_or_dietary_fit() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    ) as client:
        verified = await SourceVerifier(client, safety_check=allow_url).verify(
            _candidate("https://greenfork.example")
        )
    assert verified.verification_status == "discovered"
    assert verified.source_evidence[0].accessible is False
    assert verified.dietary_suitability == "unconfirmed"


@pytest.mark.anyio
async def test_accessible_matching_site_can_verify_source_but_not_dietary_suitability() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Green Fork Restaurant")

    result = _candidates_from_results(
        [SearchResult(url="https://greenfork.example", title="Green Fork")]
    )[0]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verified = await SourceVerifier(client, safety_check=allow_url).verify(result)
    assert verified.verification_status == "verified"
    assert verified.dietary_suitability == "unconfirmed"
    assert verified.source_evidence[0].accessible is True


@pytest.mark.anyio
async def test_unsafe_redirect_target_is_blocked() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await SourceVerifier(client, safety_check=allow_restaurant_host).verify(
            _candidate("https://greenfork.example")
        )
    assert result.source_evidence[0].accessible is False
    assert "unsafe redirect" in (result.source_evidence[0].note or "")


@pytest.mark.anyio
async def test_verifier_rejects_private_and_local_hosts_without_http_request() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("unsafe host must not be requested")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verifier = SourceVerifier(client)
        result = await verifier.verify(_candidate("http://127.0.0.1/"))
    assert result.source_evidence[0].accessible is False
    assert "unsafe" in (result.source_evidence[0].note or "")


def test_search_route_returns_structured_warning_when_key_is_missing() -> None:
    get_settings.cache_clear()
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/restaurants/search", json={"meal": "breakfast"})
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
    assert response.status_code == 200
    data = response.json()
    assert data["criteria"]["city"] == "Barcelona"
    assert data["restaurants"] == []
    assert "TAVILY_API_KEY" in data["warnings"][0]
