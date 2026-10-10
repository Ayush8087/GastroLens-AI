from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Report process liveness without depending on external services."""
    return HealthResponse(status="ok")


class ProviderStatus(BaseModel):
    name: str
    key_name: str
    configured: bool
    purpose: str


class ProviderHealthResponse(BaseModel):
    providers: list[ProviderStatus]
    live_checks_performed: bool = False


@router.get("/health/providers", response_model=ProviderHealthResponse)
def provider_health(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProviderHealthResponse:
    """Report local provider configuration without making paid external requests."""
    providers = [
        ProviderStatus(
            name="Google Places",
            key_name="GOOGLE_PLACES_API_KEY",
            configured=bool(
                settings.google_places_api_key
                and settings.google_places_api_key.get_secret_value().strip()
            ),
            purpose="Structured restaurant discovery and place identity.",
        ),
        ProviderStatus(
            name="Tavily Search",
            key_name="TAVILY_API_KEY",
            configured=bool(
                settings.tavily_api_key and settings.tavily_api_key.get_secret_value().strip()
            ),
            purpose="Restaurant discovery fallback and menu/source lookup.",
        ),
        ProviderStatus(
            name="Gemini",
            key_name="GEMINI_API_KEY",
            configured=bool(
                settings.gemini_api_key and settings.gemini_api_key.get_secret_value().strip()
            ),
            purpose="Request interpretation, menu extraction, OCR fallback, and translation.",
        ),
    ]
    return ProviderHealthResponse(providers=providers)
