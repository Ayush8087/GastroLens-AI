import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.config import Settings, get_settings
from app.integrations.gemini import GeminiResearchProvider
from app.integrations.places import GooglePlacesProvider
from app.integrations.tavily_search import TavilySearchProvider
from app.schemas.restaurant_search import RestaurantSearchRequest, RestaurantSearchResponse
from app.services.menu_research import MenuResearchService
from app.services.restaurant_discovery import RestaurantDiscoveryService
from app.services.source_verification import SourceVerifier

router = APIRouter(prefix="/api/v1/restaurants", tags=["restaurants"])


def get_discovery_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> RestaurantDiscoveryService:
    gemini = GeminiResearchProvider(
        settings.gemini_api_key,
        model=settings.gemini_model,
    )
    return RestaurantDiscoveryService(
        search_provider=TavilySearchProvider(settings.tavily_api_key),
        verifier=SourceVerifier(),
        places_provider=GooglePlacesProvider(settings.google_places_api_key),
        menu_researcher=MenuResearchService(translator=gemini, extractor=gemini),
        request_interpreter=gemini,
    )


@router.post("/search", response_model=RestaurantSearchResponse)
async def search_restaurants(
    request: RestaurantSearchRequest,
    service: Annotated[RestaurantDiscoveryService, Depends(get_discovery_service)],
) -> RestaurantSearchResponse:
    return await service.discover(request)


@router.post("/search/stream")
async def search_restaurants_stream(
    request: RestaurantSearchRequest,
    service: Annotated[RestaurantDiscoveryService, Depends(get_discovery_service)],
) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        task = asyncio.create_task(service.discover(request, progress_callback=queue.put_nowait))
        try:
            while not task.done() or not queue.empty():
                try:
                    stage = await asyncio.wait_for(queue.get(), timeout=0.2)
                    yield f"event: progress\ndata: {json.dumps({'stage': stage})}\n\n"
                except TimeoutError:
                    continue
            response = await task
            payload = response.model_dump(mode="json")
            yield f"event: result\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
            raise
        except Exception:
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
            yield (
                "event: error\ndata: "
                + json.dumps({"message": "Restaurant research could not be completed."})
                + "\n\n"
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
