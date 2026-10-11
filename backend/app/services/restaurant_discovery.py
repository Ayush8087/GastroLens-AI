import asyncio
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime

from app.integrations.gemini import GeminiProviderError, GeminiResearchProvider
from app.integrations.places import PlaceSearchProvider, PlacesProviderError
from app.integrations.search import SearchProvider
from app.integrations.tavily_search import SearchProviderError
from app.schemas.restaurant_search import (
    RestaurantCandidate,
    RestaurantSearchRequest,
    RestaurantSearchResponse,
    SourceEvidence,
)
from app.services.menu_research import MenuResearchService
from app.services.source_verification import SourceVerifier, normalize_url

logger = logging.getLogger(__name__)


class RestaurantDiscoveryService:
    def __init__(
        self,
        search_provider: SearchProvider,
        verifier: SourceVerifier,
        places_provider: PlaceSearchProvider | None = None,
        menu_researcher: MenuResearchService | None = None,
        request_interpreter: GeminiResearchProvider | None = None,
    ) -> None:
        self.search_provider = search_provider
        self.verifier = verifier
        self.places_provider = places_provider
        self.menu_researcher = menu_researcher or MenuResearchService()
        self.request_interpreter = request_interpreter

    async def discover(
        self,
        request: RestaurantSearchRequest,
        progress_callback: Callable[[str], None] | None = None,
    ) -> RestaurantSearchResponse:
        report = progress_callback or (lambda _: None)
        warnings: list[str] = []
        if request.query:
            if self.request_interpreter and self.request_interpreter.configured:
                report("Interpreting your request")
                try:
                    request = await self.request_interpreter.interpret_request(request)
                except GeminiProviderError as exc:
                    warnings.append(str(exc))
            else:
                warnings.append(
                    "GEMINI_API_KEY is not configured; basic phrase parsing is used "
                    "for the request."
                )
        report("Searching location-aware restaurant listings")
        location = request.location or _location_from_query(request.query)
        if location is None and request.latitude is not None and request.longitude is not None:
            location = "your current location"
        if not location:
            report("A location is needed before searching listings")
            return RestaurantSearchResponse(
                criteria=request,
                restaurants=[],
                warnings=[
                    *warnings,
                    "Add a location, or include one in your description (for example, ‘in Kyoto’).",
                ],
            )
        query = _search_query(request, location)
        cuisine_preferences = request.preferred_cuisines or (
            [request.preferred_cuisine] if request.preferred_cuisine else []
        )
        if request.meal or cuisine_preferences or request.party_size or request.other_preferences:
            unsupported = []
            if request.meal:
                unsupported.append("meal availability")
            if cuisine_preferences:
                unsupported.append("cuisine identity")
            if request.party_size:
                unsupported.append("party-size suitability")
            if request.other_preferences:
                unsupported.append("atmosphere and accessibility preferences")
            warnings.append(
                "These are sent as discovery hints but are not verified by current sources: "
                + ", ".join(unsupported)
                + "."
            )
        if request.search_radius_meters and request.latitude is None:
            warnings.append(
                "A radius without coordinates is used as a text search hint and cannot "
                "be enforced as an exact distance."
            )
        candidates: list[RestaurantCandidate] = []
        now = datetime.now(UTC)
        places = []
        places_failure: str | None = None
        if self.places_provider is not None:
            try:
                if request.latitude is not None and request.longitude is not None:
                    places = await self.places_provider.search_places(
                        query,
                        max_results=request.max_results,
                        location_bias={
                            "latitude": request.latitude,
                            "longitude": request.longitude,
                            "radius_meters": request.search_radius_meters or 5_000,
                        },
                    )
                else:
                    places = await self.places_provider.search_places(
                        query, max_results=request.max_results
                    )
            except PlacesProviderError as exc:
                places_failure = str(exc)
            except Exception as exc:
                logger.exception(
                    "unexpected_places_provider_failure", extra={"error_type": type(exc).__name__}
                )
                places_failure = "Google Places is temporarily unavailable."
        else:
            places_failure = "GOOGLE_PLACES_API_KEY is missing."

        fallback_reason = places_failure
        if not places and fallback_reason is None:
            fallback_reason = "Google Places returned no restaurant listings."

        if fallback_reason and self.search_provider:
            if request.latitude is not None and request.location is None:
                return RestaurantSearchResponse(
                    criteria=request,
                    restaurants=[],
                    warnings=[
                        *warnings,
                        fallback_reason,
                        "Tavily cannot discover restaurants from coordinates; configure "
                        "Google Places or enter a city or address.",
                    ],
                    provider_coverage=(
                        "Tavily web search requires a text location and does not provide "
                        "coordinate-based local discovery."
                    ),
                )
            report("Using web search fallback for restaurant leads")
            try:
                results = await self.search_provider.search(
                    query,
                    max_results=request.max_results,
                )
            except SearchProviderError as exc:
                return RestaurantSearchResponse(
                    criteria=request,
                    restaurants=[],
                    warnings=[*warnings, fallback_reason, str(exc)],
                    provider_coverage=(
                        "Google Places structured listings are unavailable. Tavily web search "
                        "also requires configuration and cannot provide structured ratings, "
                        "hours, or complete geographic coverage."
                    ),
                )
            except Exception as exc:
                logger.warning("tavily_discovery_failure", extra={"error_type": type(exc).__name__})
                return RestaurantSearchResponse(
                    criteria=request,
                    restaurants=[],
                    warnings=[
                        *warnings,
                        fallback_reason,
                        "Web search fallback is temporarily unavailable.",
                    ],
                    provider_coverage=(
                        "Google Places structured listings are unavailable; web search fallback "
                        "could not be completed."
                    ),
                )
            warnings.append(
                f"{fallback_reason} Using Tavily web results as unverified leads; addresses, "
                "ratings, hours, and geographic coverage are not guaranteed."
            )
            seen_urls: set[str] = set()
            for result in results:
                url = normalize_url(result.url)
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                name = _candidate_name(result.title, url)
                if not name:
                    continue
                is_menu = bool(
                    re.search(r"menu|carta|karte|men[uú]", f"{url} {result.title}", re.I)
                )
                candidates.append(
                    RestaurantCandidate(
                        restaurant_name=name,
                        menu_url=url if is_menu else None,
                        source_evidence=[
                            SourceEvidence(
                                url=url,
                                title=result.title or None,
                                snippet=result.snippet or None,
                                source_type="unclassified",
                                retrieved_at=now,
                                note=(
                                    "Web search lead only; listing identity and address are "
                                    "unverified."
                                ),
                            )
                        ],
                        retrieved_at=now,
                        unknown_fields=[
                            "address",
                            "official_website_url",
                            *([] if is_menu else ["menu"]),
                        ],
                    )
                )

        report(
            f"Found {len(places) if places else len(candidates)} candidates; "
            "checking sources and menus"
        )

        for place in places:
            evidence: list[SourceEvidence] = []
            if place.maps_url:
                url = normalize_url(place.maps_url)
                if url:
                    evidence.append(
                        SourceEvidence(
                            url=url,
                            title=f"{place.name} on Google Maps",
                            source_type="third_party",
                            retrieved_at=now,
                            note="Place identity and address supplied by Google Places.",
                        )
                    )
            website = normalize_url(place.website_url) if place.website_url else None
            discovered_menu = (
                website
                if website and re.search(r"menu|carta|karte|men[uú]", website, re.IGNORECASE)
                else None
            )
            if website:
                evidence.append(
                    SourceEvidence(
                        url=website,
                        title=place.name,
                        source_type="restaurant_site_candidate",
                        retrieved_at=now,
                    )
                )
            candidates.append(
                RestaurantCandidate(
                    restaurant_name=place.name,
                    city_or_address=place.address,
                    official_website_url=website,
                    menu_url=discovered_menu,
                    source_evidence=evidence,
                    retrieved_at=now,
                    unknown_fields=[
                        key
                        for key, value in (
                            ("address", place.address),
                            ("official_website_url", website),
                            ("menu", discovered_menu),
                        )
                        if value is None
                    ],
                    place_id=place.place_id,
                    maps_url=place.maps_url,
                    business_status=place.business_status,
                    latitude=place.latitude,
                    longitude=place.longitude,
                    distance_meters=(
                        _distance_meters(
                            request.latitude,
                            request.longitude,
                            place.latitude,
                            place.longitude,
                        )
                        if request.latitude is not None
                        and request.longitude is not None
                        and place.latitude is not None
                        and place.longitude is not None
                        else None
                    ),
                    location_match=(
                        "confirmed"
                        if (
                            location.casefold() in (place.address or "").casefold()
                            or (
                                request.latitude is not None
                                and request.longitude is not None
                                and place.latitude is not None
                                and place.longitude is not None
                            )
                        )
                        else "unconfirmed"
                    ),
                )
            )

        # Search is used only to locate additional source pages. A search snippet never
        # overrides Google Places identity/address data and never confirms a menu item.
        if places and self.search_provider and candidates:
            for candidate in candidates[: min(len(candidates), 5)]:
                try:
                    web_results = await self.search_provider.search(
                        f'"{candidate.restaurant_name}" {location} official menu', max_results=3
                    )
                except SearchProviderError as exc:
                    warnings.append(str(exc))
                    break
                except Exception as exc:
                    logger.warning(
                        "tavily_enrichment_failure", extra={"error_type": type(exc).__name__}
                    )
                    warnings.append("Some restaurant source pages could not be searched.")
                    break
                for result in web_results:
                    url = normalize_url(result.url)
                    if url is None:
                        continue
                    is_menu = bool(
                        re.search(
                            r"menu|carta|karte|men[uú]",
                            f"{url} {result.title}",
                            re.IGNORECASE,
                        )
                    )
                    if any(source.url == url for source in candidate.source_evidence):
                        if is_menu and candidate.menu_url is None:
                            candidate.menu_url = url
                            candidate.unknown_fields = [
                                value for value in candidate.unknown_fields if value != "menu"
                            ]
                        continue
                    candidate.source_evidence.append(
                        SourceEvidence(
                            url=url,
                            title=result.title or None,
                            snippet=result.snippet or None,
                            source_type="unclassified",
                            retrieved_at=datetime.now(UTC),
                        )
                    )
                    if candidate.menu_url is None and is_menu:
                        candidate.menu_url = url
                        candidate.unknown_fields = [
                            value for value in candidate.unknown_fields if value != "menu"
                        ]

        semaphore = asyncio.Semaphore(5)

        async def verify_candidate(candidate: RestaurantCandidate) -> RestaurantCandidate:
            async with semaphore:
                return await _verify_and_research(candidate)

        async def _verify_and_research(candidate: RestaurantCandidate) -> RestaurantCandidate:
            report(f"Checking source evidence for {candidate.restaurant_name or 'a restaurant'}")
            verified = await self.verifier.verify(candidate)
            if verified.menu_url:
                report(
                    f"Reading the discovered menu for {verified.restaurant_name or 'a restaurant'}"
                )
                try:
                    verified = await self.menu_researcher.research(verified, request)
                except Exception as exc:
                    logger.warning(
                        "menu_research_failure", extra={"error_type": type(exc).__name__}
                    )
                    warnings.append(f"Could not research the menu for {verified.restaurant_name}.")
            if verified.location_match == "unconfirmed":
                verified.match_status = "uncertain"
                verified.score = min(verified.score, 35)
                verified.match_reasons.append(
                    "The provider address does not explicitly confirm the requested location."
                )
            if (
                request.search_radius_meters
                and verified.distance_meters is not None
                and verified.distance_meters > request.search_radius_meters
            ):
                verified.match_status = "excluded"
                verified.score = 0
                verified.match_reasons.append(
                    "The Places listing is outside the requested search radius."
                )
            if verified.business_status in {"CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"}:
                verified.match_status = "excluded"
                verified.score = 0
                verified.match_reasons.append(
                    "The listing provider reports that this business is closed."
                )
            return verified

        checked = await asyncio.gather(*(verify_candidate(candidate) for candidate in candidates))
        priority = {"exact_match": 0, "partial_match": 1, "uncertain": 2, "excluded": 3}
        checked.sort(
            key=lambda item: (
                priority[item.match_status],
                -item.score,
                (item.restaurant_name or "").casefold(),
                item.place_id or "",
            )
        )
        return RestaurantSearchResponse(
            criteria=request,
            restaurants=checked,
            warnings=sorted(set(warnings)),
            provider_coverage=(
                "Tavily web search is a lower-confidence fallback and does not supply "
                "structured ratings, hours, or complete geographic coverage."
                if fallback_reason
                else "Restaurant listings are provided by Google Places. Results depend on its "
                "regional coverage and may omit businesses or current availability."
            ),
        )


def _candidate_name(title: str, url: str) -> str | None:
    cleaned = re.sub(r"\s*[|–—-]\s*(menu|official website|home)\b.*$", "", title, flags=re.I)
    cleaned = re.sub(r"\b(menu|official website|home)\b", "", cleaned, flags=re.I).strip(" -|–—")
    if len(cleaned) >= 2:
        return cleaned[:160]
    host = (url.split("//", 1)[-1].split("/", 1)[0]).removeprefix("www.")
    host = host.split(":", 1)[0]
    label = host.split(".", 1)[0].replace("-", " ").strip()
    return label.title() if len(label) >= 2 else None


def _distance_meters(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    earth_radius_meters = 6_371_000
    delta_latitude = radians(lat_b - lat_a)
    delta_longitude = radians(lon_b - lon_a)
    value = (
        sin(delta_latitude / 2) ** 2
        + cos(radians(lat_a)) * cos(radians(lat_b)) * sin(delta_longitude / 2) ** 2
    )
    return earth_radius_meters * 2 * asin(sqrt(value))


def _location_from_query(query: str | None) -> str | None:
    if not query:
        return None
    match = re.search(r"\b(?:in|near|around)\s+([^,.;!?]+)", query, re.IGNORECASE)
    if not match:
        return None
    location = match.group(1).strip()[:160]
    return None if location.casefold() in {"me", "here", "the area", "my location"} else location


def _search_query(request: RestaurantSearchRequest, location: str) -> str:
    if request.query:
        details = [f"restaurants {request.query}"]
        if request.meal:
            details.append(request.meal)
        details.extend(request.preferred_cuisines)
        if request.preferred_cuisine:
            details.append(request.preferred_cuisine)
        if request.search_radius_meters:
            details.append(f"within {request.search_radius_meters / 1000:g} km")
        details.extend(request.other_preferences)
        details.extend(request.dietary_requirements)
        details.extend(request.avoided_ingredients)
        details.extend(request.allergies)
        if request.max_budget_per_person is not None:
            details.append(
                f"under {request.max_budget_per_person:g} {request.currency or ''}".strip()
            )
        if request.party_size:
            details.append(f"for {request.party_size} people")
        if request.latitude is None:
            details.append(f"in {location}")
        return " ".join(dict.fromkeys(details))
    details = ["restaurants"]
    if request.latitude is None:
        details.append(f"in {location}")
    else:
        details.append("near current location")
    if request.meal:
        details.append(request.meal)
    details.extend(request.preferred_cuisines)
    if request.preferred_cuisine:
        details.append(request.preferred_cuisine)
    if request.search_radius_meters:
        details.append(f"within {request.search_radius_meters / 1000:g} km")
    details.extend(request.dietary_requirements)
    details.extend(request.avoided_ingredients)
    details.extend(request.allergies)
    if request.max_budget_per_person is not None:
        details.append(f"under {request.max_budget_per_person:g} {request.currency or ''}".strip())
    if request.party_size:
        details.append(f"for {request.party_size} people")
    details.extend(request.other_preferences)
    return " ".join(details)
