import asyncio
import base64
import json
import logging
import re
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.schemas.restaurant_search import MenuItem, RestaurantSearchRequest

logger = logging.getLogger(__name__)

CONSTRAINTS_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "location": {"type": "string"},
        "search_radius_meters": {"type": "integer"},
        "meal": {"type": "string", "enum": ["breakfast", "brunch", "lunch", "supper", "dinner"]},
        "preferred_cuisine": {"type": "string"},
        "dietary_requirements": {"type": "array", "items": {"type": "string"}},
        "avoided_ingredients": {"type": "array", "items": {"type": "string"}},
        "allergies": {"type": "array", "items": {"type": "string"}},
        "max_budget_per_person": {"type": "number"},
        "currency": {"type": "string"},
        "target_language": {"type": "string"},
        "other_preferences": {"type": "array", "items": {"type": "string"}},
        "party_size": {"type": "integer"},
    },
}
MENU_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "section": {"type": "string"},
                },
                "required": ["quote"],
            },
        }
    },
    "required": ["items"],
}
TRANSLATION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name"],
            },
        }
    },
    "required": ["translations"],
}


class GeminiProviderError(Exception):
    """Safe error for Gemini failures; provider payloads and keys are never exposed."""


class ParsedConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str | None = None
    search_radius_meters: int | None = Field(default=None, ge=100, le=50_000)
    meal: Literal["breakfast", "brunch", "lunch", "supper", "dinner"] | None = None
    preferred_cuisine: str | None = None
    dietary_requirements: list[str] = Field(default_factory=list, max_length=8)
    avoided_ingredients: list[str] = Field(default_factory=list, max_length=30)
    allergies: list[str] = Field(default_factory=list, max_length=20)
    max_budget_per_person: float | None = Field(default=None, gt=0, le=100_000)
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    target_language: str | None = None
    other_preferences: list[str] = Field(default_factory=list, max_length=12)
    party_size: int | None = Field(default=None, ge=1, le=50)


class MenuEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote: str = Field(min_length=3, max_length=500)
    section: str | None = Field(default=None, max_length=100)


class MenuEvidenceList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MenuEvidence] = Field(default_factory=list, max_length=100)


class TranslationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=400)


class TranslationList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    translations: list[TranslationItem] = Field(max_length=100)


class GeminiResearchProvider:
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(
        self,
        api_key: SecretStr | None,
        *,
        model: str = "gemini-3.8-flash",
        client: httpx.AsyncClient | None = None,
        attempts: int = 2,
        retry_delay: float = 0.2,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.client = client
        self.attempts = max(1, min(attempts, 2))
        self.retry_delay = max(0.0, min(retry_delay, 1.0))

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_key.get_secret_value().strip())

    async def interpret_request(self, request: RestaurantSearchRequest) -> RestaurantSearchRequest:
        if not request.query or not self.configured:
            return request
        prompt = (
            "Extract only constraints explicitly stated in the user's restaurant request. "
            "Do not infer a location from 'near me', dietary facts, currency, or preferences. "
            "Return JSON fields location, search_radius_meters, meal, preferred_cuisine, "
            "dietary_requirements, avoided_ingredients, allergies, max_budget_per_person, "
            "currency, target_language, party_size, other_preferences. "
            "Use null or [] when unstated. "
            "Request: " + json.dumps(request.query, ensure_ascii=False)
        )
        try:
            parsed = ParsedConstraints.model_validate(
                await self._generate_json(prompt, CONSTRAINTS_SCHEMA)
            )
        except (GeminiProviderError, ValidationError) as exc:
            if isinstance(exc, GeminiProviderError):
                raise
            raise GeminiProviderError("Gemini returned invalid request constraints.") from exc

        query = request.query.casefold()
        updates: dict[str, object] = {}
        if request.location is None and _appears_in_query(parsed.location, query):
            if parsed.location and parsed.location.casefold() not in {"me", "here", "near me"}:
                updates["location"] = parsed.location.strip()
        if request.search_radius_meters is None and parsed.search_radius_meters is not None:
            if re.search(rf"\b{parsed.search_radius_meters}\b", query):
                updates["search_radius_meters"] = parsed.search_radius_meters
        if request.meal is None and parsed.meal and re.search(rf"\b{parsed.meal}\b", query):
            updates["meal"] = parsed.meal
        if (
            request.preferred_cuisine is None
            and not request.preferred_cuisines
            and _appears_in_query(parsed.preferred_cuisine, query)
        ):
            updates["preferred_cuisine"] = parsed.preferred_cuisine
        for field in ("dietary_requirements", "avoided_ingredients", "allergies"):
            present = getattr(request, field)
            if present:
                continue
            grounded = [
                value for value in getattr(parsed, field) if _appears_in_query(value, query)
            ]
            if grounded:
                updates[field] = list(dict.fromkeys([*present, *grounded]))
        if request.max_budget_per_person is None and parsed.max_budget_per_person is not None:
            amount = f"{parsed.max_budget_per_person:g}"
            if amount in request.query.replace(",", "."):
                updates["max_budget_per_person"] = parsed.max_budget_per_person
        if request.currency is None and parsed.currency:
            if parsed.currency.casefold() in query:
                updates["currency"] = parsed.currency.upper()
            elif parsed.currency.upper() == "INR" and "₹" in request.query:
                updates["currency"] = "INR"
        if request.target_language is None and _appears_in_query(parsed.target_language, query):
            updates["target_language"] = parsed.target_language
        if request.party_size is None and parsed.party_size is not None:
            if re.search(rf"\b{parsed.party_size}\s+(?:people|persons|guests|diners)\b", query):
                updates["party_size"] = parsed.party_size
        if parsed.other_preferences:
            updates["other_preferences"] = list(
                dict.fromkeys(
                    [*request.other_preferences]
                    + [
                        value
                        for value in parsed.other_preferences
                        if _appears_in_query(value, query)
                    ]
                )
            )
        if not updates:
            return request
        return RestaurantSearchRequest.model_validate({**request.model_dump(), **updates})

    async def extract_menu_evidence(
        self,
        text: str,
        *,
        document: bytes | None = None,
        mime_type: str | None = None,
    ) -> list[MenuEvidence]:
        if not self.configured:
            raise GeminiProviderError("Gemini is not configured (GEMINI_API_KEY is missing).")
        prompt = (
            "Find menu entries and return only exact source quotes that contain a printed dish "
            "name and price. Do not infer or normalize prices or currency. Each quote must be "
            "copied verbatim from the supplied source. Include a section only when its exact "
            "label appears in the source. If no priced dish is supported, return {items: []}.\n"
            "Source text:\n" + text[:30_000]
        )
        parts: list[dict[str, object]] = [{"text": prompt}]
        if document and mime_type and mime_type == "application/pdf" and len(document) <= 2_000_000:
            parts.append(
                {
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": base64.b64encode(document).decode("ascii"),
                    }
                }
            )
        try:
            parsed = MenuEvidenceList.model_validate(
                await self._generate_json_parts(parts, MENU_SCHEMA)
            )
            return parsed.items
        except (GeminiProviderError, ValidationError) as exc:
            if isinstance(exc, GeminiProviderError):
                raise
            raise GeminiProviderError("Gemini returned invalid menu extraction data.") from exc

    async def translate(self, items: list[MenuItem], language: str) -> bool:
        if not items:
            return True
        if not self.configured:
            return False
        prompt = (
            "Translate only these menu names and descriptions to "
            + json.dumps(language)
            + ". Preserve meaning. Do not add ingredients, prices, dietary claims, or details. "
            "Return a JSON object with a translations array in the same order. Input: "
            + json.dumps(
                [{"name": item.name, "description": item.description} for item in items],
                ensure_ascii=False,
            )
        )
        try:
            result = TranslationList.model_validate(
                await self._generate_json(prompt, TRANSLATION_SCHEMA)
            )
        except (GeminiProviderError, ValidationError) as exc:
            if isinstance(exc, GeminiProviderError):
                logger.info(
                    "gemini_translation_unavailable", extra={"error_type": type(exc).__name__}
                )
                return False
            return False
        if len(result.translations) != len(items):
            return False
        for original, translated in zip(items, result.translations, strict=True):
            original.translated_text = translated.name
            original.translated_description = translated.description
        return True

    async def _generate_json(self, prompt: str, schema: dict[str, object]) -> object:
        return await self._generate_json_parts([{"text": prompt}], schema)

    async def _generate_json_parts(
        self, parts: list[dict[str, object]], schema: dict[str, object]
    ) -> object:
        if not self.configured:
            raise GeminiProviderError("Gemini is not configured (GEMINI_API_KEY is missing).")
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 8192,
                "responseFormat": {"text": {"mimeType": "application/json", "schema": schema}},
            },
        }
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(
            timeout=httpx.Timeout(20.0), follow_redirects=False, trust_env=False
        )
        try:
            for attempt in range(self.attempts):
                try:
                    response = await client.post(
                        self.endpoint.format(model=self.model),
                        headers={"x-goog-api-key": self.api_key.get_secret_value()},
                        json=payload,
                    )
                    if response.status_code == 429 or _is_quota_response(response):
                        if attempt + 1 < self.attempts:
                            await asyncio.sleep(self.retry_delay * (2**attempt))
                            continue
                        raise GeminiProviderError("Gemini rate limit or quota was exceeded.")
                    if response.status_code >= 500:
                        if attempt + 1 < self.attempts:
                            await asyncio.sleep(self.retry_delay * (2**attempt))
                            continue
                        raise GeminiProviderError("Gemini is temporarily unavailable.")
                    if response.status_code in {400, 401, 403}:
                        raise GeminiProviderError(
                            "Gemini rejected the request or configured credentials. Check "
                            "GEMINI_API_KEY and GEMINI_MODEL."
                        )
                    response.raise_for_status()
                    try:
                        body = response.json()
                    except ValueError as exc:
                        raise GeminiProviderError("Gemini returned malformed JSON.") from exc
                    candidates = body.get("candidates") if isinstance(body, dict) else None
                    first_candidate = (
                        candidates[0]
                        if isinstance(candidates, list)
                        and candidates
                        and isinstance(candidates[0], dict)
                        else None
                    )
                    content = first_candidate.get("content") if first_candidate else None
                    response_parts = content.get("parts") if isinstance(content, dict) else None
                    response_text = next(
                        (
                            part.get("text")
                            for part in response_parts or []
                            if isinstance(part, dict) and isinstance(part.get("text"), str)
                        ),
                        None,
                    )
                    if not response_text:
                        raise GeminiProviderError("Gemini returned an empty structured response.")
                    try:
                        return json.loads(response_text)
                    except json.JSONDecodeError as exc:
                        raise GeminiProviderError(
                            "Gemini returned malformed structured data."
                        ) from exc
                except httpx.TimeoutException as exc:
                    if attempt + 1 == self.attempts:
                        raise GeminiProviderError("Gemini request timed out.") from exc
                    await asyncio.sleep(self.retry_delay * (2**attempt))
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        "gemini_http_failure", extra={"status_code": exc.response.status_code}
                    )
                    raise GeminiProviderError("Gemini request failed.") from exc
                except httpx.HTTPError as exc:
                    if attempt + 1 == self.attempts:
                        logger.warning(
                            "gemini_transport_failure", extra={"error_type": type(exc).__name__}
                        )
                        raise GeminiProviderError("Gemini is temporarily unavailable.") from exc
                    await asyncio.sleep(self.retry_delay * (2**attempt))
            raise GeminiProviderError("Gemini is temporarily unavailable.")
        finally:
            if owns_client:
                await client.aclose()


def _appears_in_query(value: str | None, query: str) -> bool:
    return bool(value and value.strip() and value.casefold() in query)


def _is_quota_response(response: httpx.Response) -> bool:
    if response.status_code not in {400, 403}:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    error = body.get("error") if isinstance(body, dict) else None
    status = error.get("status") if isinstance(error, dict) else None
    return isinstance(status, str) and status.casefold() in {
        "resource_exhausted",
        "quota_exceeded",
    }
