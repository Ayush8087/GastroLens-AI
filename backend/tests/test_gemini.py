import json
from datetime import UTC, datetime

import httpx
import pymupdf
import pytest
from pydantic import SecretStr

from app.integrations.gemini import GeminiProviderError, GeminiResearchProvider
from app.schemas.restaurant_search import RestaurantCandidate, RestaurantSearchRequest
from app.services.menu_research import MenuResearchService


def _gemini_response(value: object) -> httpx.Response:
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": json.dumps(value)}]}}]},
    )


@pytest.mark.anyio
async def test_gemini_interpretation_only_applies_values_grounded_in_user_text() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "test-key"
        return _gemini_response(
            {
                "location": "Kyoto",
                "meal": "dinner",
                "preferred_cuisine": "Italian",
                "dietary_requirements": ["vegan"],
                "avoided_ingredients": [],
                "allergies": [],
                "max_budget_per_person": 900,
                "currency": "INR",
                "target_language": None,
                "other_preferences": ["quiet anniversary", "rooftop"],
            }
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = GeminiResearchProvider(SecretStr("test-key"), client=client)
        result = await provider.interpret_request(
            RestaurantSearchRequest(query="A vegan dinner in Kyoto for a quiet anniversary")
        )
    assert result.location == "Kyoto"
    assert result.meal == "dinner"
    assert result.dietary_requirements == ["vegan"]
    assert result.preferred_cuisine is None
    assert result.max_budget_per_person is None
    assert result.currency is None
    assert result.other_preferences == ["quiet anniversary"]


@pytest.mark.anyio
async def test_explicit_filter_values_take_precedence_over_conflicting_parsed_values() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return _gemini_response(
            {
                "location": "Kyoto",
                "meal": "dinner",
                "preferred_cuisine": "Italian",
                "dietary_requirements": ["vegetarian"],
                "avoided_ingredients": [],
                "allergies": [],
                "max_budget_per_person": None,
                "currency": None,
                "target_language": None,
                "other_preferences": [],
                "party_size": None,
            }
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await GeminiResearchProvider(
            SecretStr("test-key"), client=client
        ).interpret_request(
            RestaurantSearchRequest(
                query="Find vegetarian dinner in Kyoto",
                dietary_requirements=["Vegan"],
                preferred_cuisines=["Assamese"],
                meal="brunch",
            )
        )

    assert result.meal == "brunch"
    assert result.dietary_requirements == ["Vegan"]
    assert result.preferred_cuisine is None
    assert result.preferred_cuisines == ["Assamese"]


@pytest.mark.anyio
async def test_menu_extraction_accepts_only_exact_source_quotes_and_translation_is_separate() -> (
    None
):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "restaurant.example":
            return httpx.Response(
                200,
                text=("<h1>Nori</h1><h2>VEGAN MENU</h2><p>Vegan tofu bowl — sesame EUR 12.00</p>"),
                headers={"content-type": "text/html"},
            )
        payload = json.loads(request.content)
        prompt = payload["contents"][0]["parts"][0]["text"]
        if prompt.startswith("Find individual dish entries"):
            return _gemini_response(
                {
                    "items": [
                        {"quote": "Vegan tofu bowl EUR 0.00", "section": "VEGAN MENU"},
                        {
                            "quote": "Vegan tofu bowl — sesame EUR 12.00",
                            "section": "VEGAN MENU",
                        },
                    ]
                }
            )
        return _gemini_response(
            {"translations": [{"name": "Tofu bowl", "description": "With sesame"}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gemini = GeminiResearchProvider(SecretStr("test-key"), client=client)
        candidate = RestaurantCandidate(
            restaurant_name="Nori",
            official_website_url="https://restaurant.example/",
            menu_url="https://restaurant.example/menu",
            verification_status="verified",
            source_evidence=[],
            retrieved_at=datetime.now(UTC),
        )
        result = await MenuResearchService(
            client,
            translator=gemini,
            extractor=gemini,
            safety_check=lambda _: _allow_url(),
        ).research(
            candidate,
            RestaurantSearchRequest(
                location="Kyoto",
                dietary_requirements=["vegan"],
                target_language="English",
            ),
        )
    assert len(result.menu_items) == 1
    item = result.menu_items[0]
    assert item.name == "Vegan tofu bowl"
    assert item.price == 12.0
    assert item.currency == "EUR"
    assert item.evidence == "Vegan tofu bowl — sesame EUR 12.00"
    assert item.translated_text == "Tofu bowl"
    assert item.translated_description == "With sesame"
    assert item.dietary_status == "confirmed"


@pytest.mark.anyio
async def test_gemini_can_return_an_exactly_quoted_dish_without_a_price() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["contents"][0]["parts"][0]["text"]
        assert "whether or not a price is printed" in prompt
        return _gemini_response(
            {
                "items": [
                    {
                        "quote": "Focaccia rustica with rosemary",
                        "name": "Focaccia rustica",
                        "section": "Antipasti",
                    }
                ]
            }
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await GeminiResearchProvider(
            SecretStr("test-key"), client=client
        ).extract_menu_evidence("Antipasti\nFocaccia rustica with rosemary")
    assert len(items) == 1
    assert items[0].quote == "Focaccia rustica with rosemary"
    assert items[0].name == "Focaccia rustica"


async def _allow_url() -> bool:
    return True


@pytest.mark.anyio
async def test_gemini_missing_key_and_quota_errors_are_clear_and_safe() -> None:
    with pytest.raises(GeminiProviderError, match="GEMINI_API_KEY"):
        await GeminiResearchProvider(None).extract_menu_evidence("menu text")

    async def rate_limited(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "private provider payload"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(rate_limited)) as client:
        provider = GeminiResearchProvider(SecretStr("test-key"), client=client, attempts=1)
        with pytest.raises(GeminiProviderError, match="quota") as error:
            await provider.interpret_request(RestaurantSearchRequest(query="Dinner in Kyoto"))
    assert "private provider payload" not in str(error.value)


@pytest.mark.anyio
async def test_scanned_pdf_extraction_remains_unverified_and_cannot_confirm_budget_match() -> None:
    document = pymupdf.open()
    document.new_page()
    pdf_bytes = document.tobytes()
    document.close()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "restaurant.example":
            return httpx.Response(
                200, content=pdf_bytes, headers={"content-type": "application/pdf"}
            )
        return _gemini_response({"items": [{"quote": "Vegan bowl EUR 8.00", "section": "Dinner"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gemini = GeminiResearchProvider(SecretStr("test-key"), client=client)
        candidate = RestaurantCandidate(
            restaurant_name="Nori",
            official_website_url="https://restaurant.example/",
            menu_url="https://restaurant.example/menu.pdf",
            verification_status="verified",
            source_evidence=[],
            retrieved_at=datetime.now(UTC),
        )
        result = await MenuResearchService(
            client,
            translator=gemini,
            extractor=gemini,
            safety_check=lambda _: _allow_url(),
        ).research(
            candidate,
            RestaurantSearchRequest(
                dietary_requirements=["vegan"],
                max_budget_per_person=20,
                currency="EUR",
            ),
        )

    assert result.menu_items[0].evidence_type == "ocr_transcription"
    assert result.menu_items[0].price == 8
    assert result.menu_items[0].dietary_status == "unknown"
    assert result.menu_items[0].extraction_confidence == 0.5
    assert result.match_status == "uncertain"
    assert any("OCR-derived" in warning for warning in result.menu_items[0].warnings)
