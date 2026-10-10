import re
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlsplit

import httpx
import pymupdf
from bs4 import BeautifulSoup

from app.integrations.translation import OpenAITranslationProvider
from app.schemas.restaurant_search import MenuItem, RestaurantCandidate, RestaurantSearchRequest
from app.services.source_verification import _is_public_http_url, normalize_url

MAX_MENU_BYTES = 2_000_000
MAX_PDF_PAGES = 50
PRICE_PATTERN = re.compile(
    r"(?P<name>.+?)\s+(?:(?P<prefix_code>[A-Z]{3})\s+)?"
    r"(?P<symbol>€|£|\$)?\s*(?P<amount>\d{1,5}(?:[.,]\d{1,2})?)\s*"
    r"(?P<code>[A-Z]{3})?\s*$",
)


class MenuResearchService:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        translator: OpenAITranslationProvider | None = None,
        safety_check: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self.client = client
        self.translator = translator
        self.safety_check = safety_check or _is_public_http_url

    async def research(
        self, candidate: RestaurantCandidate, request: RestaurantSearchRequest
    ) -> RestaurantCandidate:
        url = candidate.menu_url
        if not url:
            candidate.match_reasons = ["No menu source was located."]
            candidate.match_status = "uncertain"
            return candidate
        content, content_type, final_url = await self._fetch(url)
        if content is None:
            candidate.match_reasons = ["A menu link was found but could not be accessed safely."]
            candidate.match_status = "uncertain"
            return candidate
        try:
            text = _extract_text(content, content_type, final_url)
        except (ValueError, RuntimeError, pymupdf.FileDataError):
            text = ""
        website_host = (
            (urlsplit(candidate.official_website_url or "").hostname or "")
            .lower()
            .removeprefix("www.")
        )
        menu_host = (urlsplit(final_url).hostname or "").lower().removeprefix("www.")
        if (
            candidate.restaurant_name
            and website_host != menu_host
            and candidate.restaurant_name.casefold() not in text.casefold()
        ):
            candidate.match_status = "uncertain"
            candidate.score = 0
            candidate.match_reasons = [
                "Menu source could not be matched to this restaurant's identity."
            ]
            return candidate
        candidate.menu_items = _parse_menu_lines(text, final_url, request)
        translation_unavailable = False
        if request.target_language and candidate.menu_items:
            translation_unavailable = (
                self.translator is None
                or not await self.translator.translate(
                    candidate.menu_items, request.target_language
                )
            )
        candidate.match_status, candidate.score, candidate.match_reasons = _score_candidate(
            candidate.menu_items, request
        )
        if translation_unavailable:
            candidate.match_reasons.append(
                "Translation is unavailable; original menu text is shown. Configure OPENAI_API_KEY."
            )
        if not candidate.menu_items:
            candidate.match_reasons = [
                "Menu page was reached, but no clearly priced dish lines could be extracted."
            ]
        return candidate

    async def _fetch(self, url: str) -> tuple[bytes | None, str, str]:
        normalized = normalize_url(url)
        if not normalized:
            return None, "", url
        owns_client = self.client is None
        client = (
            self.client
            if self.client is not None
            else httpx.AsyncClient(
                timeout=httpx.Timeout(8.0), follow_redirects=False, trust_env=False
            )
        )
        current = normalized
        try:
            for _ in range(4):
                if not await self.safety_check(current):
                    return None, "", current
                async with client.stream("GET", current, follow_redirects=False) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        target = normalize_url(urljoin(current, location or ""))
                        if not target or not await self.safety_check(target):
                            return None, "", current
                        current = target
                        continue
                    if not 200 <= response.status_code < 300:
                        return None, "", current
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        remaining = MAX_MENU_BYTES - len(data)
                        if remaining <= 0:
                            break
                        data.extend(chunk[:remaining])
                    return bytes(data), response.headers.get("content-type", ""), current
            return None, "", current
        except (httpx.HTTPError, OSError, TimeoutError):
            return None, "", current
        finally:
            if owns_client:
                await client.aclose()


def _extract_text(content: bytes, content_type: str, url: str) -> str:
    is_pdf = "pdf" in content_type.lower() or urlsplit(url).path.lower().endswith(".pdf")
    if is_pdf:
        with pymupdf.open(stream=content, filetype="pdf") as document:
            if document.page_count > MAX_PDF_PAGES:
                return ""
            return "\n".join(page.get_text("text") for page in document)
    soup = BeautifulSoup(content, "html.parser")
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()
    return soup.get_text("\n", strip=True)


def _parse_menu_lines(
    text: str, source_url: str, request: RestaurantSearchRequest
) -> list[MenuItem]:
    items: list[MenuItem] = []
    seen: set[str] = set()
    section: str | None = None
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split()).strip(" •·-–—")
        if not line or len(line) > 240:
            continue
        found = PRICE_PATTERN.fullmatch(line)
        if not found:
            if len(line) < 45 and line.isupper() and not re.search(r"\d", line):
                section = line.title()
            continue
        raw_name = found.group("name").strip(" .-–—•")
        parts = re.split(r"\s+(?:—|–|\|)\s+", raw_name, maxsplit=1)
        name = parts[0]
        description = parts[1] if len(parts) > 1 else ""
        name = name.strip(" .-–—•")
        if len(name) < 3 or len(name) > 120 or not re.search(r"[A-Za-zÀ-ÿ]", name):
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        symbol = found.group("symbol")
        code = found.group("code") or found.group("prefix_code")
        currency = (
            code.upper() if code else "EUR" if symbol == "€" else "GBP" if symbol == "£" else None
        )
        amount = float(found.group("amount").replace(",", "."))
        status, warnings = _dietary_status(line, request)
        items.append(
            MenuItem(
                name=name,
                original_text=line,
                description=description.strip() or None,
                price=amount,
                currency=currency,
                section=section,
                source_url=source_url,
                evidence=line,
                dietary_status=status,
                warnings=warnings,
            )
        )
    return items[:100]


def _dietary_status(line: str, request: RestaurantSearchRequest) -> tuple[str, list[str]]:
    folded = line.casefold()
    contradicted = [
        value
        for value in (*request.allergies, *request.avoided_ingredients)
        if re.search(rf"\b{re.escape(value.casefold())}\b", folded)
    ]
    if contradicted:
        return "contradicted", [
            f"Menu text contains requested avoid term: {term}." for term in contradicted
        ]
    if not request.dietary_requirements:
        return "unknown", []
    explicit = [
        requirement
        for requirement in request.dietary_requirements
        if re.search(rf"\b{re.escape(requirement)}\b", folded)
    ]
    if len(explicit) == len(request.dietary_requirements):
        return "confirmed", [
            "Menu line explicitly labels this dish with the requested dietary terms."
        ]
    return "unknown", ["Menu text does not explicitly establish dietary suitability."]


def _score_candidate(
    items: list[MenuItem], request: RestaurantSearchRequest
) -> tuple[str, int, list[str]]:
    if not items:
        return "uncertain", 0, ["No source-backed priced dishes were extracted."]
    eligible = [item for item in items if item.dietary_status != "contradicted"]
    if not eligible:
        return "excluded", 0, ["All extracted dishes contain a user-specified avoid term."]
    reasons: list[str] = []
    budget_known = request.max_budget_per_person is None
    budget_match = request.max_budget_per_person is None
    budget_has_uncomparable_items = False
    comparable_prices: list[float] = []
    for item in eligible:
        if request.max_budget_per_person is not None:
            if item.currency and request.currency and item.currency == request.currency:
                budget_known = True
                if item.price is not None:
                    comparable_prices.append(item.price)
                    if item.price <= request.max_budget_per_person:
                        budget_match = True
                        reasons.append(
                            f"{item.name} is within the stated budget at its printed price."
                        )
            elif not request.currency:
                budget_has_uncomparable_items = True
                reasons.append("Budget cannot be checked until a currency is specified.")
            else:
                budget_has_uncomparable_items = True
                reasons.append(
                    "Printed price currency is missing or differs from the requested currency."
                )
    if request.meal or request.preferred_cuisine:
        reasons.append("Meal timing or cuisine has not been independently verified.")
    confirmed = any(item.dietary_status == "confirmed" for item in eligible)
    other_constraints_verified = not request.meal and not request.preferred_cuisine
    if (
        confirmed
        and budget_known
        and budget_match
        and other_constraints_verified
        and not request.allergies
        and not request.avoided_ingredients
    ):
        return (
            "exact_match",
            90,
            list(dict.fromkeys(reasons or ["Menu evidence confirms the requested dietary label."])),
        )
    if (
        comparable_prices
        and not budget_match
        and not budget_has_uncomparable_items
        and not request.allergies
        and not request.avoided_ingredients
    ):
        return (
            "excluded",
            0,
            list(dict.fromkeys(reasons or ["Printed prices exceed the requested budget."])),
        )
    if eligible and (
        all(item.dietary_status == "unknown" for item in eligible)
        or request.allergies
        or request.avoided_ingredients
        or (request.max_budget_per_person is not None and request.currency is None)
        or request.meal is not None
        or request.preferred_cuisine is not None
    ):
        return (
            "uncertain",
            35,
            list(
                dict.fromkeys(
                    reasons or ["Dietary suitability is not established by menu evidence."]
                )
            ),
        )
    return (
        "partial_match",
        60,
        list(dict.fromkeys(reasons or ["Some constraints remain unverified."])),
    )
