import asyncio
import logging
from typing import Protocol

import httpx
from pydantic import SecretStr

logger = logging.getLogger(__name__)


class PlaceRecord:
    def __init__(
        self,
        *,
        place_id: str,
        name: str,
        address: str | None,
        website_url: str | None,
        maps_url: str | None,
        business_status: str | None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> None:
        self.place_id = place_id
        self.name = name
        self.address = address
        self.website_url = website_url
        self.maps_url = maps_url
        self.business_status = business_status
        self.latitude = latitude
        self.longitude = longitude


class PlaceSearchProvider(Protocol):
    async def search_places(
        self,
        query: str,
        *,
        max_results: int,
        location_bias: dict[str, float] | None = None,
    ) -> list[PlaceRecord]: ...


class PlacesProviderError(Exception):
    """Safe error raised for unavailable or malformed place-provider results."""


class GooglePlacesProvider:
    endpoint = "https://places.googleapis.com/v1/places:searchText"
    field_mask = ",".join(
        (
            "places.id",
            "places.displayName",
            "places.formattedAddress",
            "places.websiteUri",
            "places.googleMapsUri",
            "places.businessStatus",
            "places.location",
        )
    )

    def __init__(
        self,
        api_key: SecretStr | None,
        *,
        client: httpx.AsyncClient | None = None,
        attempts: int = 2,
        retry_delay: float = 0.2,
    ) -> None:
        self.api_key = api_key
        self.client = client
        self.attempts = max(1, min(attempts, 2))
        self.retry_delay = max(0.0, min(retry_delay, 1.0))

    async def search_places(
        self,
        query: str,
        *,
        max_results: int = 10,
        location_bias: dict[str, float] | None = None,
    ) -> list[PlaceRecord]:
        if self.api_key is None or not self.api_key.get_secret_value().strip():
            raise PlacesProviderError(
                "Restaurant discovery is not configured (GOOGLE_PLACES_API_KEY is missing)."
            )
        owns_client = self.client is None
        client = (
            self.client
            if self.client is not None
            else httpx.AsyncClient(timeout=httpx.Timeout(12.0), trust_env=False)
        )
        try:
            payload: dict[str, object] = {
                "textQuery": query,
                "pageSize": max(1, min(max_results, 20)),
            }
            if location_bias:
                payload["locationBias"] = {
                    "circle": {
                        "center": {
                            "latitude": location_bias["latitude"],
                            "longitude": location_bias["longitude"],
                        },
                        "radius": location_bias["radius_meters"],
                    }
                }
            response: httpx.Response | None = None
            for attempt in range(self.attempts):
                try:
                    response = await client.post(
                        self.endpoint,
                        headers={
                            "X-Goog-Api-Key": self.api_key.get_secret_value(),
                            "X-Goog-FieldMask": self.field_mask,
                        },
                        json=payload,
                    )
                except httpx.TimeoutException:
                    if attempt + 1 == self.attempts:
                        raise
                    await asyncio.sleep(self.retry_delay * (2**attempt))
                    continue
                except httpx.HTTPError:
                    if attempt + 1 == self.attempts:
                        raise
                    await asyncio.sleep(self.retry_delay * (2**attempt))
                    continue
                if (
                    response.status_code == 429
                    or response.status_code >= 500
                    or _is_quota_response(response)
                ) and attempt + 1 < self.attempts:
                    await asyncio.sleep(self.retry_delay * (2**attempt))
                    continue
                break
            if response is None:
                raise PlacesProviderError("Restaurant location search is temporarily unavailable.")
            if response.status_code == 429 or _is_quota_response(response):
                raise PlacesProviderError("Google Places rate limit or quota was exceeded.")
            if response.status_code in {401, 403}:
                raise PlacesProviderError("Google Places rejected the configured credentials.")
            if response.status_code >= 500:
                raise PlacesProviderError("Restaurant location search is temporarily unavailable.")
            response.raise_for_status()
            payload = response.json()
            places = payload.get("places") if isinstance(payload, dict) else None
            if not isinstance(places, list):
                raise PlacesProviderError("Google Places returned a malformed response.")
            output: list[PlaceRecord] = []
            seen_place_ids: set[str] = set()
            for place in places[: max(1, min(max_results, 20))]:
                if not isinstance(place, dict):
                    continue
                display_name = place.get("displayName")
                name = display_name.get("text") if isinstance(display_name, dict) else None
                place_id = place.get("id")
                if not isinstance(name, str) or not name.strip() or not isinstance(place_id, str):
                    continue
                if place_id in seen_place_ids:
                    continue
                seen_place_ids.add(place_id)
                output.append(
                    PlaceRecord(
                        place_id=place_id,
                        name=name.strip(),
                        address=_optional_text(place.get("formattedAddress")),
                        website_url=_optional_text(place.get("websiteUri")),
                        maps_url=_optional_text(place.get("googleMapsUri")),
                        business_status=_optional_text(place.get("businessStatus")),
                        latitude=_coordinate(place.get("location"), "latitude"),
                        longitude=_coordinate(place.get("location"), "longitude"),
                    )
                )
            if places and not output:
                raise PlacesProviderError("Google Places returned malformed place records.")
            return output
        except httpx.TimeoutException as exc:
            raise PlacesProviderError("Restaurant location search timed out.") from exc
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "places_http_failure",
                extra={"status_code": exc.response.status_code},
            )
            raise PlacesProviderError("Restaurant location search failed.") from exc
        except httpx.HTTPError as exc:
            logger.warning("places_transport_failure", extra={"error_type": type(exc).__name__})
            raise PlacesProviderError(
                "Restaurant location search is temporarily unavailable."
            ) from exc
        except ValueError as exc:
            raise PlacesProviderError("Google Places returned invalid JSON.") from exc
        finally:
            if owns_client:
                await client.aclose()


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _coordinate(value: object, key: str) -> float | None:
    if not isinstance(value, dict):
        return None
    coordinate = value.get(key)
    return float(coordinate) if isinstance(coordinate, (int, float)) else None


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
