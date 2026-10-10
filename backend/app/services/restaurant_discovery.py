import logging
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

from app.integrations.search import SearchProvider
from app.integrations.tavily_search import SearchProviderError
from app.schemas.restaurant_search import (
    RestaurantCandidate,
    RestaurantSearchRequest,
    RestaurantSearchResponse,
    SearchResult,
    SourceEvidence,
)
from app.services.source_verification import SourceVerifier, normalize_url

logger = logging.getLogger(__name__)


class RestaurantDiscoveryService:
    def __init__(self, search_provider: SearchProvider, verifier: SourceVerifier) -> None:
        self.search_provider = search_provider
        self.verifier = verifier

    async def discover(self, request: RestaurantSearchRequest) -> RestaurantSearchResponse:
        queries = _build_queries(request)
        warnings: list[str] = []
        results: list[SearchResult] = []
        for query in queries:
            try:
                results.extend(await self.search_provider.search(query, max_results=5))
            except SearchProviderError as exc:
                warnings.append(str(exc))
                logger.warning(
                    "restaurant_search_provider_failure",
                    extra={"query_category": _query_category(query)},
                )
                break
            except Exception as exc:
                warnings.append("Restaurant search is temporarily unavailable.")
                logger.exception(
                    "unexpected_search_provider_failure", extra={"error_type": type(exc).__name__}
                )
                break
        candidates = _candidates_from_results(results)
        if not candidates and warnings:
            return RestaurantSearchResponse(
                criteria=request, restaurants=[], warnings=list(dict.fromkeys(warnings))
            )
        candidates = candidates[: request.max_results]
        verified = [await self.verifier.verify(candidate) for candidate in candidates]
        return RestaurantSearchResponse(
            criteria=request,
            restaurants=verified,
            warnings=list(dict.fromkeys(warnings)),
        )


def _build_queries(request: RestaurantSearchRequest) -> list[str]:
    food_terms = " ".join(request.dietary_requirements)
    cuisine = f" {request.preferred_cuisine}" if request.preferred_cuisine else ""
    base = f"{food_terms}{cuisine} restaurants {request.meal} in {request.city}"
    queries = [base, f"{base} official website", f"{base} menu carta"]
    if request.max_budget_per_person is not None:
        queries[0] += f" under {request.max_budget_per_person:g} {request.currency} per person"
    return queries


def _query_category(query: str) -> str:
    return "menu" if "menu" in query else "official" if "official" in query else "discovery"


def _candidates_from_results(results: list[SearchResult]) -> list[RestaurantCandidate]:
    now = datetime.now(UTC)
    candidates: list[RestaurantCandidate] = []
    by_url: dict[str, RestaurantCandidate] = {}
    for result in results:
        normalized = normalize_url(result.url)
        if normalized is None:
            continue
        existing = by_url.get(normalized)
        name = _name_from_title(result.title)
        source_type = _source_type(normalized, name)
        evidence = SourceEvidence(
            url=normalized,
            title=result.title or None,
            snippet=result.snippet or None,
            source_type=source_type,
            retrieved_at=now,
        )
        if existing:
            if all(source.url != normalized for source in existing.source_evidence):
                existing.source_evidence.append(evidence)
            if not existing.menu_url and _looks_like_menu(normalized, result.title):
                existing.menu_url = normalized
            continue
        candidate = RestaurantCandidate(
            restaurant_name=name,
            official_website_url=None,
            menu_url=normalized if _looks_like_menu(normalized, result.title) else None,
            source_evidence=[evidence],
            retrieved_at=now,
            unknown_fields=[],
        )
        candidate.unknown_fields = _unknown_fields(candidate)
        identity_match = next(
            (item for item in candidates if _same_restaurant_identity(item, candidate)),
            None,
        )
        if identity_match is not None:
            identity_match.source_evidence.append(evidence)
            if identity_match.menu_url is None:
                identity_match.menu_url = candidate.menu_url
            by_url[normalized] = identity_match
            continue
        by_url[normalized] = candidate
        candidates.append(candidate)
    return candidates


def _source_type(url: str, name: str | None) -> str:
    host = (urlsplit(url).hostname or "").lower()
    directory_hosts = (
        "tripadvisor.",
        "yelp.",
        "thefork.",
        "google.",
        "facebook.",
        "instagram.",
        "wanderlog.",
    )
    if any(domain in host for domain in directory_hosts):
        return "third_party"
    if name:
        name_tokens = {token for token in re.findall(r"[a-z0-9]+", name.lower()) if len(token) > 2}
        site_host = host.removeprefix("www.")
        host_label = re.sub(r"[^a-z0-9]", "", site_host.split(".")[0])
        name_compact = "".join(re.findall(r"[a-z0-9]+", name.lower()))
        host_tokens = set(re.findall(r"[a-z0-9]+", site_host.split(".")[0]))
        if name_tokens and (
            name_tokens.issubset(host_tokens)
            or (len(name_compact) > 3 and name_compact in host_label)
        ):
            return "restaurant_site_candidate"
    return "unclassified"


def _name_from_title(title: str) -> str | None:
    if title:
        name = re.split(r"\s(?:\||–|—|::|·)\s", title, maxsplit=1)[0].strip()
        name = re.sub(r"\s+(?:menu|carta|official website)$", "", name, flags=re.IGNORECASE)
        if name:
            return name[:160]
    return None


def _unknown_fields(candidate: RestaurantCandidate) -> list[str]:
    missing = [
        field
        for field, value in (
            ("restaurant_name", candidate.restaurant_name),
            ("city_or_address", candidate.city_or_address),
            ("official_website_url", candidate.official_website_url),
            ("menu_url", candidate.menu_url),
        )
        if value is None
    ]
    missing.extend(["restaurant_identity", "vegetarian_suitability"])
    return missing


def _same_restaurant_identity(first: RestaurantCandidate, second: RestaurantCandidate) -> bool:
    if not first.restaurant_name or not second.restaurant_name:
        return False
    if not first.city_or_address or not second.city_or_address:
        return False
    normalized_name = " ".join(re.findall(r"[a-z0-9]+", first.restaurant_name.casefold()))
    second_name = " ".join(re.findall(r"[a-z0-9]+", second.restaurant_name.casefold()))
    normalized_address = " ".join(re.findall(r"[a-z0-9]+", first.city_or_address.casefold()))
    second_address = " ".join(re.findall(r"[a-z0-9]+", second.city_or_address.casefold()))
    first_host = (urlsplit(first.source_evidence[0].url).hostname or "").removeprefix("www.")
    second_host = (urlsplit(second.source_evidence[0].url).hostname or "").removeprefix("www.")
    return (
        normalized_name == second_name
        and normalized_address == second_address
        and first_host == second_host
    )


def _looks_like_menu(url: str, title: str) -> bool:
    return bool(re.search(r"menu|carta", f"{url} {title}", re.IGNORECASE))
