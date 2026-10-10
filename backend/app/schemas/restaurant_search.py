import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Meal = Literal["breakfast", "lunch", "dinner"]
VerificationStatus = Literal["discovered", "partially_verified", "verified"]


class RestaurantSearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    city: str = Field(default="Barcelona", min_length=1, max_length=100)
    meal: Meal
    dietary_requirements: list[str] = Field(
        default_factory=lambda: ["vegetarian"], min_length=1, max_length=8
    )
    preferred_cuisine: str | None = Field(default=None, min_length=1, max_length=80)
    max_budget_per_person: float | None = Field(default=None, gt=0, le=100_000)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    max_results: int = Field(default=10, ge=1, le=20)

    @field_validator("dietary_requirements")
    @classmethod
    def normalize_dietary_requirements(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(value.strip().lower() for value in values if value.strip()))
        if not cleaned:
            raise ValueError("at least one dietary requirement is required")
        if any(len(value) > 50 for value in cleaned):
            raise ValueError("dietary requirements must be at most 50 characters")
        return cleaned

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.upper()
        if re.fullmatch(r"[A-Z]{3}", value) is None:
            raise ValueError("currency must be a three-letter code")
        return value


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


class RestaurantSearchResponse(BaseModel):
    criteria: RestaurantSearchRequest
    restaurants: list[RestaurantCandidate]
    warnings: list[str] = Field(default_factory=list)
