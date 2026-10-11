import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Meal = Literal["breakfast", "brunch", "lunch", "supper", "dinner"]
VerificationStatus = Literal["discovered", "partially_verified", "verified"]


class RestaurantSearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str | None = Field(default=None, min_length=3, max_length=500)
    location: str | None = Field(default=None, min_length=2, max_length=160)
    search_radius_meters: int | None = Field(default=None, ge=100, le=50_000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    meal: Meal | None = None
    dietary_requirements: list[str] = Field(default_factory=list, max_length=8)
    avoided_ingredients: list[str] = Field(default_factory=list, max_length=30)
    allergies: list[str] = Field(default_factory=list, max_length=20)
    target_language: str | None = Field(default=None, min_length=2, max_length=40)
    other_preferences: list[str] = Field(default_factory=list, max_length=12)
    preferred_cuisine: str | None = Field(default=None, min_length=1, max_length=80)
    preferred_cuisines: list[str] = Field(default_factory=list, max_length=8)
    party_size: int | None = Field(default=None, ge=1, le=50)
    max_budget_per_person: float | None = Field(default=None, gt=0, le=100_000)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    max_results: int = Field(default=10, ge=1, le=20)

    @field_validator("query", "location", "preferred_cuisine", "target_language")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("dietary_requirements")
    @classmethod
    def normalize_dietary_requirements(cls, values: list[str]) -> list[str]:
        cleaned = _unique_terms(values)
        if any(len(value) > 50 for value in cleaned):
            raise ValueError("dietary requirements must be at most 50 characters")
        return cleaned

    @field_validator("avoided_ingredients", "allergies", "other_preferences")
    @classmethod
    def normalize_terms(cls, values: list[str]) -> list[str]:
        cleaned = _unique_terms(values)
        if any(len(value) > 70 for value in cleaned):
            raise ValueError("each ingredient or allergy term must be at most 70 characters")
        return cleaned

    @field_validator("preferred_cuisines")
    @classmethod
    def normalize_cuisines(cls, values: list[str]) -> list[str]:
        cleaned = _unique_terms(values)
        if any(len(value) > 80 for value in cleaned):
            raise ValueError("each cuisine must be at most 80 characters")
        return cleaned

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.upper()
        if re.fullmatch(r"[A-Z]{3}", value) is None:
            raise ValueError("currency must be a three-letter code")
        return value

    @model_validator(mode="after")
    def parse_obvious_query_constraints(self) -> "RestaurantSearchRequest":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        if not self.query:
            return self
        folded = self.query.casefold()
        if self.meal is None:
            for meal in ("breakfast", "brunch", "lunch", "supper", "dinner"):
                if re.search(rf"\b{meal}\b", folded):
                    self.meal = meal  # type: ignore[assignment]
                    break
        if not self.dietary_requirements:
            found = [
                term
                for term in ("vegetarian", "vegan", "halal", "kosher", "gluten-free")
                if re.search(rf"\b{re.escape(term)}\b", folded)
            ]
            self.dietary_requirements = found
        if not self.location:
            match = re.search(
                r"\b(?:in|near|around)\s+([^,.!?]+?)(?=\s+(?:for|with|under|and|that|who)\b|[,!?]|$)",
                self.query,
                re.IGNORECASE,
            )
            if match and match.group(1).strip().casefold() not in {
                "the mood",
                "the area",
                "me",
                "here",
            }:
                self.location = match.group(1).strip()[:160]
        if self.preferred_cuisine is None and not self.preferred_cuisines:
            cuisine = re.search(r"\b([\w-]{2,40})\s+cuisine\b", self.query, re.IGNORECASE)
            if cuisine:
                self.preferred_cuisine = cuisine.group(1)
        if self.max_budget_per_person is None:
            budget = re.search(
                r"\b(?:under|up to|maximum|max|budget(?: of)?)\s*([$€£₹])?\s*"
                r"(\d{1,6}(?:[.,]\d{1,2})?)\s*([A-Z]{3})?\b",
                self.query,
                re.IGNORECASE,
            )
            if budget:
                amount = float(budget.group(2).replace(",", "."))
                if amount <= 100_000:
                    self.max_budget_per_person = amount
                    if self.currency is None and budget.group(3):
                        self.currency = budget.group(3).upper()
                    elif self.currency is None and budget.group(1) == "€":
                        self.currency = "EUR"
                    elif self.currency is None and budget.group(1) == "£":
                        self.currency = "GBP"
                    elif self.currency is None and budget.group(1) == "₹":
                        self.currency = "INR"
        if self.search_radius_meters is None:
            radius = re.search(
                r"\bwithin\s+(\d{1,2}(?:\.\d+)?)\s*(km|kilomet(?:er|re)s?)\b", folded
            )
            if radius and 0.1 <= float(radius.group(1)) <= 50:
                self.search_radius_meters = int(float(radius.group(1)) * 1000)
        if not self.allergies:
            allergy = re.search(
                r"\ballergic to\s+([\w -]{2,50}?)(?=\s+(?:in|near|around|for|under|with)\b"
                r"|[,.;!?]|$)",
                self.query,
                re.IGNORECASE,
            )
            if allergy:
                self.allergies = [allergy.group(1).strip()]
        if not self.avoided_ingredients:
            avoided = re.search(
                r"\b(?:avoid|without|no)\s+([\w -]{2,50}?)(?=\s+(?:in|near|around|for|under|with)\b"
                r"|[,.;!?]|$)",
                self.query,
                re.IGNORECASE,
            )
            if avoided:
                self.avoided_ingredients = [avoided.group(1).strip()]
        return self


def _unique_terms(values: list[str]) -> list[str]:
    """Trim whitespace, preserve wording, and remove case-insensitive duplicates."""
    unique: dict[str, str] = {}
    for raw in values:
        value = raw.strip()
        if value:
            unique.setdefault(value.casefold(), value)
    return list(unique.values())


class SearchResult(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""


class SourceEvidence(BaseModel):
    url: str
    final_url: str | None = None
    title: str | None = None
    snippet: str | None = None
    source_type: Literal["restaurant_site_candidate", "third_party", "unclassified"] = (
        "unclassified"
    )
    retrieved_at: datetime
    accessible: bool | None = None
    http_status: int | None = None
    note: str | None = None


class MenuItem(BaseModel):
    name: str
    original_text: str
    translated_text: str | None = None
    translated_description: str | None = None
    description: str | None = None
    price: float | None = Field(default=None, ge=0, le=1_000_000)
    currency: str | None = None
    section: str | None = None
    source_url: str
    evidence: str
    evidence_type: Literal["printed_text", "ocr_transcription"] = "printed_text"
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    dietary_status: Literal["confirmed", "contradicted", "unknown"] = "unknown"
    allergen_status: Literal["conflict", "unknown"] = "unknown"
    warnings: list[str] = Field(default_factory=list)


class RestaurantCandidate(BaseModel):
    restaurant_name: str | None = None
    city_or_address: str | None = None
    official_website_url: str | None = None
    menu_url: str | None = None
    source_evidence: list[SourceEvidence]
    retrieved_at: datetime
    verification_status: VerificationStatus = "discovered"
    verification_evidence: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    dietary_suitability: Literal["unconfirmed"] = "unconfirmed"
    place_id: str | None = None
    maps_url: str | None = None
    business_status: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    distance_meters: float | None = None
    location_match: Literal["confirmed", "unconfirmed"] = "unconfirmed"
    menu_items: list[MenuItem] = Field(default_factory=list)
    match_status: Literal["exact_match", "partial_match", "uncertain", "excluded"] = "uncertain"
    score: int = 0
    match_reasons: list[str] = Field(default_factory=list)


class RestaurantSearchResponse(BaseModel):
    criteria: RestaurantSearchRequest
    restaurants: list[RestaurantCandidate]
    warnings: list[str] = Field(default_factory=list)
    provider_coverage: str = "Coverage depends on the configured location provider."
