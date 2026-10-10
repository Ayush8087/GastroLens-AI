from datetime import UTC, datetime

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.api.routes.restaurants import get_discovery_service
from app.core.config import Settings, get_settings
from app.integrations.places import GooglePlacesProvider, PlaceRecord, PlacesProviderError
from app.integrations.tavily_search import SearchProviderError, TavilySearchProvider
from app.integrations.translation import OpenAITranslationProvider
from app.main import app
from app.schemas.restaurant_search import (
    MenuItem,
    RestaurantCandidate,
    RestaurantSearchRequest,
    SearchResult,
)
from app.services.menu_research import (
    MenuResearchService,
    _extract_text,
    _parse_menu_lines,
    _score_candidate,
)
from app.services.restaurant_discovery import RestaurantDiscoveryService
from app.services.source_verification import SourceVerifier, normalize_url


class StaticSearchProvider:
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


class StaticPlacesProvider:
    def __init__(self, places: list[PlaceRecord] | None = None) -> None:
        self.places = places or []
        self.query = ""

    async def search_places(self, query: str, *, max_results: int) -> list[PlaceRecord]:
        self.query = query
        return self.places[:max_results]


async def allow_url(_: str) -> bool:
    return True


def _place() -> PlaceRecord:
    return PlaceRecord(
        place_id="places/abc123",
        name="Garden Table",
        address="12 Market Street, Kyoto",
        website_url="https://gardentable.example/menu",
        maps_url="https://maps.example/place/abc123",
        business_status="OPERATIONAL",
    )


def test_request_has_no_location_diet_or_currency_defaults_and_parses_obvious_terms() -> None:
    request = RestaurantSearchRequest(query="vegetarian dinner in Kyoto under 20")
    assert request.location == "Kyoto"
    assert request.meal == "dinner"
    assert request.dietary_requirements == ["vegetarian"]
    assert request.currency is None
    assert request.max_budget_per_person == 20
    assert RestaurantSearchRequest(query="dinner in Osaka, allergic to peanuts").allergies == [
        "peanuts"
    ]
    assert normalize_url("javascript:alert(1)") is None
    assert normalize_url("https://user:password@example.com") is None
    with pytest.raises(ValidationError):
        RestaurantSearchRequest(max_results=21)


@pytest.mark.anyio
async def test_google_places_provider_parses_live_provider_contract_deterministically() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Goog-Api-Key"] == "test-key"
        assert "places.formattedAddress" in request.headers["X-Goog-FieldMask"]
        return httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "places/1",
                        "displayName": {"text": "Nori"},
                        "formattedAddress": "Kyoto",
                        "websiteUri": "https://nori.example",
                        "businessStatus": "OPERATIONAL",
                    },
                    {
                        "id": "places/1",
                        "displayName": {"text": "Nori duplicate"},
                        "formattedAddress": "Kyoto",
                    },
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        places = await GooglePlacesProvider(SecretStr("test-key"), client=client).search_places(
            "restaurants in Kyoto", max_results=10
        )
    assert len(places) == 1
    assert places[0].name == "Nori"
    assert places[0].address == "Kyoto"


@pytest.mark.anyio
async def test_google_places_missing_credentials_are_explicit() -> None:
    with pytest.raises(PlacesProviderError, match="GOOGLE_PLACES_API_KEY"):
        await GooglePlacesProvider(None).search_places("restaurants in Kyoto", max_results=10)


@pytest.mark.anyio
async def test_tavily_missing_credentials_and_malformed_payload_are_clear() -> None:
    with pytest.raises(SearchProviderError, match="TAVILY_API_KEY"):
        await TavilySearchProvider(None).search("menu")

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answer": "not results"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = TavilySearchProvider(SecretStr("test-key"), client=client, attempts=1)
        with pytest.raises(SearchProviderError, match="malformed"):
            await provider.search("menu")


@pytest.mark.anyio
async def test_tavily_rate_limit_retries_are_bounded() -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = TavilySearchProvider(
            SecretStr("test-key"), client=client, attempts=20, retry_delay=0
        )
        with pytest.raises(SearchProviderError, match="temporarily unavailable"):
            await provider.search("menu")
    assert calls == 3


@pytest.mark.anyio
async def test_google_places_outage_is_reported_without_results() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = GooglePlacesProvider(SecretStr("test-key"), client=client)
        with pytest.raises(PlacesProviderError, match="temporarily unavailable"):
            await provider.search_places("restaurants in Kyoto", max_results=10)


@pytest.mark.anyio
async def test_real_search_vertical_slice_keeps_location_identity_and_menu_evidence() -> None:
    search = StaticSearchProvider(
        [SearchResult(url="https://gardentable.example/menu", title="Garden Table menu")]
    )
    places = StaticPlacesProvider([_place()])

    async def page(request: httpx.Request) -> httpx.Response:
        if request.url.host == "gardentable.example":
            return httpx.Response(
                200,
                text=(
                    "<html><body><h1>Garden Table</h1><h2>SMALL PLATES</h2>"
                    "<p>Vegan mushroom toast — with thyme €14.00</p>"
                    "<p>Seasonal soup €9.50</p></body></html>"
                ),
                headers={"content-type": "text/html"},
            )
        return httpx.Response(200, text="Garden Table listing")

    async with httpx.AsyncClient(transport=httpx.MockTransport(page)) as client:
        service = RestaurantDiscoveryService(
            search_provider=search,
            verifier=SourceVerifier(client, safety_check=allow_url),
            places_provider=places,
            menu_researcher=MenuResearchService(client, safety_check=allow_url),
        )
        response = await service.discover(
            RestaurantSearchRequest(location="Kyoto", dietary_requirements=["vegan"])
        )
    assert places.query == "restaurants Kyoto vegan"
    assert len(response.restaurants) == 1
    candidate = response.restaurants[0]
    assert candidate.restaurant_name == "Garden Table"
    assert candidate.city_or_address == "12 Market Street, Kyoto"
    assert candidate.menu_items[0].name == "Vegan mushroom toast"
    assert candidate.menu_items[0].description == "with thyme"
    assert candidate.menu_items[0].price == 14.0
    assert candidate.menu_items[0].currency == "EUR"
    assert candidate.menu_items[0].dietary_status == "confirmed"
    assert candidate.match_status == "exact_match"
    assert candidate.menu_items[0].evidence == "Vegan mushroom toast — with thyme €14.00"


def test_http_search_route_returns_provider_backed_restaurant_data() -> None:
    async def page(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Garden Table restaurant")

    async_client = httpx.AsyncClient(transport=httpx.MockTransport(page))
    service = RestaurantDiscoveryService(
        search_provider=StaticSearchProvider(),
        verifier=SourceVerifier(async_client, safety_check=allow_url),
        places_provider=StaticPlacesProvider([_place()]),
    )
    app.dependency_overrides[get_discovery_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/restaurants/search",
                json={"location": "Kyoto", "meal": "dinner"},
            )
    finally:
        app.dependency_overrides.clear()
        import asyncio

        asyncio.run(async_client.aclose())
    assert response.status_code == 200
    body = response.json()
    assert body["restaurants"][0]["place_id"] == "places/abc123"
    assert body["restaurants"][0]["city_or_address"] == "12 Market Street, Kyoto"
    assert body["restaurants"][0]["match_status"] == "uncertain"


def test_streaming_route_emits_progress_and_final_result_events() -> None:
    place = PlaceRecord(
        place_id="place-stream",
        name="Nori",
        address="Kyoto",
        website_url=None,
        maps_url=None,
        business_status="OPERATIONAL",
    )
    service = RestaurantDiscoveryService(
        StaticSearchProvider(),
        SourceVerifier(safety_check=allow_url),
        StaticPlacesProvider([place]),
    )
    app.dependency_overrides[get_discovery_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/restaurants/search/stream", json={"location": "Kyoto"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "event: progress" in response.text
    assert '"stage": "Found 1 listing candidates' in response.text
    assert "event: result" in response.text
    assert '"place_id": "place-stream"' in response.text


@pytest.mark.anyio
async def test_missing_location_and_provider_outage_return_no_fabricated_results() -> None:
    no_location = RestaurantDiscoveryService(
        StaticSearchProvider(), SourceVerifier(), StaticPlacesProvider()
    )
    result = await no_location.discover(RestaurantSearchRequest(query="a cozy dinner"))
    assert result.restaurants == []
    assert "Add a location" in result.warnings[0]

    async def failure(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(failure)) as client:
        provider = GooglePlacesProvider(SecretStr("key"), client=client)
        with pytest.raises(PlacesProviderError, match="temporarily unavailable"):
            await provider.search_places("restaurants in Kyoto", max_results=5)


@pytest.mark.anyio
async def test_provider_address_outside_requested_location_remains_uncertain() -> None:
    place = PlaceRecord(
        place_id="place-outside",
        name="Garden Table",
        address="Osaka",
        website_url=None,
        maps_url=None,
        business_status="OPERATIONAL",
    )
    service = RestaurantDiscoveryService(
        StaticSearchProvider(),
        SourceVerifier(safety_check=allow_url),
        StaticPlacesProvider([place]),
    )
    response = await service.discover(
        RestaurantSearchRequest(location="Kyoto", dietary_requirements=["vegan"])
    )
    assert response.restaurants[0].location_match == "unconfirmed"
    assert response.restaurants[0].match_status == "uncertain"


@pytest.mark.anyio
async def test_tavily_outage_preserves_place_results_and_adds_warning() -> None:
    place = PlaceRecord(
        place_id="place-1",
        name="Nori",
        address="Kyoto",
        website_url=None,
        maps_url=None,
        business_status="OPERATIONAL",
    )
    service = RestaurantDiscoveryService(
        StaticSearchProvider(error=SearchProviderError("Tavily is offline")),
        SourceVerifier(safety_check=allow_url),
        StaticPlacesProvider([place]),
    )
    response = await service.discover(RestaurantSearchRequest(location="Kyoto"))
    assert len(response.restaurants) == 1
    assert response.warnings == ["Tavily is offline"]


def test_menu_evidence_does_not_infer_dietary_or_allergy_safety_or_currency() -> None:
    request = RestaurantSearchRequest(
        location="Kyoto",
        dietary_requirements=["vegetarian"],
        allergies=["sesame"],
        max_budget_per_person=20,
    )
    items = _parse_menu_lines(
        "Vegetarian curry $12.00\nSesame noodles 10.50\nPlain rice 4.00",
        "https://restaurant.example/menu",
        request,
    )
    assert items[0].dietary_status == "confirmed"
    assert items[0].currency is None  # Dollar sign alone cannot identify a currency.
    assert items[1].dietary_status == "contradicted"
    assert items[2].dietary_status == "unknown"


def test_budget_matching_needs_matching_explicit_currency() -> None:
    request = RestaurantSearchRequest(
        location="Kyoto",
        dietary_requirements=["vegetarian"],
        max_budget_per_person=20,
        currency="USD",
    )
    items = _parse_menu_lines("Vegetarian curry €12.00", "https://restaurant.example/menu", request)
    assert items[0].currency == "EUR"
    assert items[0].dietary_status == "confirmed"
    status, _, _ = _score_candidate(items, request)
    assert status == "partial_match"

    yen = _parse_menu_lines("Tofu bowl JPY 1400", "https://restaurant.example/menu", request)
    assert yen[0].currency == "JPY"
    assert _score_candidate(yen, request)[0] == "uncertain"


def test_pdf_menu_text_is_extracted_with_printed_evidence() -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Vegetarian lentil bowl EUR 15.00")
    pdf_bytes = document.tobytes()
    document.close()
    text = _extract_text(pdf_bytes, "application/pdf", "https://restaurant.example/menu.pdf")
    assert "Vegetarian lentil bowl EUR 15.00" in text


@pytest.mark.anyio
async def test_translation_output_cannot_change_source_evidence_or_matching_facts() -> None:
    async def hallucinating_translation(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"translations":["Gluten-free vegan feast USD 0"]}'}}
                ]
            },
        )

    item = MenuItem(
        name="Soup",
        original_text="Soup with dairy EUR 12.00",
        price=12,
        currency="EUR",
        source_url="https://restaurant.example/menu",
        evidence="Soup with dairy EUR 12.00",
        dietary_status="contradicted",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(hallucinating_translation)
    ) as client:
        translator = OpenAITranslationProvider(SecretStr("test-key"), client=client)
        assert await translator.translate([item], "English")
    assert item.translated_text == "Gluten-free vegan feast USD 0"
    assert item.evidence == "Soup with dairy EUR 12.00"
    assert item.price == 12
    assert item.currency == "EUR"
    assert item.dietary_status == "contradicted"


@pytest.mark.anyio
async def test_wrong_restaurant_menu_identity_is_not_used() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<p>Completely Different Cafe</p><p>Vegan bowl EUR 12.00</p>",
            headers={"content-type": "text/html"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        candidate = RestaurantCandidate(
            restaurant_name="Garden Table",
            official_website_url="https://gardentable.example",
            menu_url="https://other.example/menu",
            source_evidence=[],
            retrieved_at=datetime.now(UTC),
        )
        result = await MenuResearchService(client, safety_check=allow_url).research(
            candidate,
            RestaurantSearchRequest(location="Kyoto", dietary_requirements=["vegan"]),
        )
    assert result.menu_items == []
    assert result.match_status == "uncertain"
    assert "identity" in result.match_reasons[0]


@pytest.mark.anyio
async def test_menu_redirect_to_private_network_is_blocked() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    async def safety(url: str) -> bool:
        return "127.0.0.1" not in url

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        research = MenuResearchService(client, safety_check=safety)
        candidate = RestaurantCandidate(
            restaurant_name="Nori",
            menu_url="https://restaurant.example/menu",
            source_evidence=[],
            retrieved_at=datetime.now(UTC),
        )
        result = await research.research(candidate, RestaurantSearchRequest(location="Kyoto"))
    assert result.menu_items == []
    assert result.match_status == "uncertain"


def test_search_route_reports_missing_provider_configuration() -> None:
    get_settings.cache_clear()
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/restaurants/search", json={"location": "Kyoto"})
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
    assert response.status_code == 200
    data = response.json()
    assert data["criteria"]["location"] == "Kyoto"
    assert data["restaurants"] == []
    assert "GOOGLE_PLACES_API_KEY" in data["warnings"][0]
