from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.integrations.tavily_search import TavilySearchProvider
from app.schemas.restaurant_search import RestaurantSearchRequest, RestaurantSearchResponse
from app.services.restaurant_discovery import RestaurantDiscoveryService
from app.services.source_verification import SourceVerifier

router = APIRouter(prefix="/api/v1/restaurants", tags=["restaurants"])


def get_discovery_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> RestaurantDiscoveryService:
    return RestaurantDiscoveryService(
        search_provider=TavilySearchProvider(settings.tavily_api_key),
        verifier=SourceVerifier(),
    )


@router.post("/search", response_model=RestaurantSearchResponse)
async def search_restaurants(
    request: RestaurantSearchRequest,
    service: Annotated[RestaurantDiscoveryService, Depends(get_discovery_service)],
) -> RestaurantSearchResponse:
    return await service.discover(request)
