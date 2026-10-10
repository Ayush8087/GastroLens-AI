import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

import httpx
import pymupdf
from bs4 import BeautifulSoup

from app.integrations.gemini import GeminiProviderError, GeminiResearchProvider
from app.schemas.restaurant_search import (
    MenuItem,
    RestaurantCandidate,
    RestaurantSearchRequest,
    SourceEvidence,
)
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
        translator: GeminiResearchProvider | None = None,
        extractor: GeminiResearchProvider | None = None,
        safety_check: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self.client = client
        self.translator = translator
        self.extractor = extractor or translator
        self.safety_check = safety_check or _is_public_http_url

    async def research(
        self, candidate: RestaurantCandidate, request: RestaurantSearchRequest
    ) -> RestaurantCandidate:
        url = candidate.menu_url
        if not url and candidate.official_website_url:
            url = await self._discover_menu_link(candidate)
        if not url:
            candidate.match_reasons = ["No menu source was located."]
            candidate.match_status = "uncertain"
            return candidate
        candidate.menu_url = url
        candidate.unknown_fields = [value for value in candidate.unknown_fields if value != "menu"]
        content, content_type, final_url = await self._fetch(url)
        if content is None:
            candidate.match_reasons = ["A menu link was found but could not be accessed safely."]
            candidate.match_status = "uncertain"
            return candidate
        normalized_final_url = normalize_url(final_url)
        for evidence in candidate.source_evidence:
            if normalize_url(evidence.url) == url:
                evidence.accessible = True
                evidence.final_url = normalized_final_url
        try:
            text = _extract_text(content, content_type, final_url)
        except (ValueError, RuntimeError, pymupdf.FileDataError):
            text = ""
        is_pdf = (
            "pdf" in content_type.lower()
            or final_url.lower().endswith(".pdf")
            or content.lstrip().startswith(b"%PDF-")
        )
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
        official_host = (
            (urlsplit(candidate.official_website_url or "").hostname or "")
            .lower()
            .removeprefix("www.")
        )
        menu_is_official = (
            candidate.verification_status == "verified"
            and bool(official_host)
            and official_host == menu_host
        )
        if not menu_is_official:
            for item in candidate.menu_items:
                if item.dietary_status == "confirmed":
                    item.dietary_status = "unknown"
                    item.warnings.append(
                        "The menu source is not a verified official restaurant page; "
                        "its dietary label is unconfirmed."
                    )
        extraction_warning: str | None = None
        extractor_configured = bool(getattr(self.extractor, "configured", False))
        vision_fallback = bool(
            not candidate.menu_items and is_pdf and _pdf_within_ocr_limits(content)
        )
        if self.extractor and extractor_configured:
            try:
                extracted = await self.extractor.extract_menu_evidence(
                    text,
                    document=content if vision_fallback else None,
                    mime_type=("application/pdf" if vision_fallback else None),
                )
                grounded_items: list[MenuItem] = []
                seen_evidence: set[str] = set()
                for evidence in extracted:
                    exact_text_match = evidence.quote in text
                    if (
                        not exact_text_match and not vision_fallback
                    ) or evidence.quote in seen_evidence:
                        continue
                    parsed_items = _parse_menu_lines(evidence.quote, final_url, request)
                    if not parsed_items:
                        continue
                    item = parsed_items[0]
                    if not menu_is_official and item.dietary_status == "confirmed":
                        item.dietary_status = "unknown"
                        item.warnings.append(
                            "The menu source is not a verified official restaurant page; "
                            "its dietary label is unconfirmed."
                        )
                    if evidence.section and evidence.section.casefold() in text.casefold():
                        item.section = evidence.section
                    if not exact_text_match:
                        item.evidence_type = "ocr_transcription"
                        item.extraction_confidence = 0.5
                        item.dietary_status = "unknown"
                        item.allergen_status = "unknown"
                        item.warnings.append(
                            "OCR-derived from a scanned menu and not independently "
                            "text-verifiable; confirm dish and price with the restaurant."
                        )
                    else:
                        item.extraction_confidence = 1.0
                    grounded_items.append(item)
                    seen_evidence.add(evidence.quote)
                if grounded_items:
                    candidate.menu_items = grounded_items
            except GeminiProviderError:
                extraction_warning = (
                    "Gemini extraction was unavailable; conservative printed-line parsing was used."
                )
        translation_unavailable = False
        if request.target_language and candidate.menu_items:
            translation_unavailable = (
                self.translator is None
                or not bool(getattr(self.translator, "configured", True))
                or not await self.translator.translate(
                    candidate.menu_items, request.target_language
                )
            )
        candidate.match_status, candidate.score, candidate.match_reasons = _score_candidate(
            candidate.menu_items, request
        )
        if translation_unavailable:
            candidate.match_reasons.append(
                "Translation is unavailable; original menu text is shown. Configure GEMINI_API_KEY."
            )
        if extraction_warning:
            candidate.match_reasons.append(extraction_warning)
        if not extractor_configured:
            candidate.match_reasons.append(
                "Gemini menu extraction is not configured; conservative printed-line "
                "parsing was used."
            )
        if not candidate.menu_items:
            candidate.match_reasons.append(
                "Menu page was reached, but no clearly priced dish lines could be extracted."
            )
        return candidate

    async def _discover_menu_link(self, candidate: RestaurantCandidate) -> str | None:
        website = normalize_url(candidate.official_website_url or "")
        if not website or not await self.safety_check(website):
            return None
        content, content_type, final_url = await self._fetch(website)
        if content is None or "html" not in content_type.lower():
            return None
        soup = BeautifulSoup(content, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href")
            if not isinstance(href, str):
                continue
            title = anchor.get_text(" ", strip=True)
            resolved = normalize_url(urljoin(final_url, href))
            if not resolved or not await self.safety_check(resolved):
                continue
            label = f"{title} {resolved}"
            if not re.search(
                r"menu|men[uú]|carta|karte|speisekarte|\.pdf(?:$|[?#])",
                label,
                re.IGNORECASE,
            ):
                continue
            website_host = (urlsplit(website).hostname or "").lower().removeprefix("www.")
            menu_host = (urlsplit(resolved).hostname or "").lower().removeprefix("www.")
            candidate.source_evidence.append(
                SourceEvidence(
                    url=resolved,
                    title=title or "Menu link",
                    source_type=(
                        "restaurant_site_candidate" if website_host == menu_host else "unclassified"
                    ),
                    retrieved_at=datetime.now(UTC),
                    note=(
                        "Discovered as a menu link on the restaurant website; menu content "
                        "not yet verified."
                    ),
                )
            )
            return resolved
        return None

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
    is_pdf = (
        "pdf" in content_type.lower()
        or urlsplit(url).path.lower().endswith(".pdf")
        or content.lstrip().startswith(b"%PDF-")
    )
    if is_pdf:
        with pymupdf.open(stream=content, filetype="pdf") as document:
            if document.page_count > MAX_PDF_PAGES:
                return ""
            return "\n".join(page.get_text("text") for page in document)
    soup = BeautifulSoup(content, "html.parser")
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()
    return soup.get_text("\n", strip=True)


def _pdf_within_ocr_limits(content: bytes) -> bool:
    if len(content) > MAX_MENU_BYTES:
        return False
    try:
        with pymupdf.open(stream=content, filetype="pdf") as document:
            return document.page_count <= MAX_PDF_PAGES
    except (ValueError, RuntimeError, pymupdf.FileDataError):
        return False


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
                allergen_status=(
                    "conflict"
                    if any(_term_is_present(line, term) for term in request.allergies)
                    else "unknown"
                ),
                warnings=warnings,
            )
        )
        if request.allergies and items[-1].allergen_status == "unknown":
            items[-1].warnings.append(
                "Allergen safety is unknown from this menu line; confirm with the restaurant."
            )
    return items[:100]


def _dietary_status(line: str, request: RestaurantSearchRequest) -> tuple[str, list[str]]:
    folded = line.casefold()
    contradicted = [
        value
        for value in (*request.allergies, *request.avoided_ingredients)
        if _term_is_present(folded, value)
    ]
    if contradicted:
        return "contradicted", [
            f"Menu text contains requested avoid term: {term}." for term in contradicted
        ]
    negated = [
        requirement
        for requirement in request.dietary_requirements
        if (
            re.search(
                rf"\b(?:not|non[-\s])\s+(?:certified\s+|suitable\s+for\s+)?{re.escape(requirement)}\b",
                folded,
            )
            or re.search(rf"\b{re.escape(requirement)}[- ]free\b", folded)
        )
    ]
    if negated:
        return "contradicted", [
            f"Menu text explicitly negates the requested dietary label: {term}." for term in negated
        ]
    if not request.dietary_requirements:
        return "unknown", []
    explicit = [
        requirement
        for requirement in request.dietary_requirements
        if re.search(rf"\b{re.escape(requirement)}\b", folded)
    ]
    if len(explicit) == len(request.dietary_requirements):
        uncertified = [
            requirement
            for requirement in request.dietary_requirements
            if requirement.casefold() in {"halal", "kosher"}
        ]
        if uncertified:
            return "unknown", [
                "Menu text contains a halal/kosher label, but certification or suitability "
                "is not independently verified."
            ]
        return "confirmed", [
            "Menu line explicitly labels this dish with the requested dietary terms."
        ]
    return "unknown", ["Menu text does not explicitly establish dietary suitability."]


def _term_is_present(text: str, term: str) -> bool:
    for match in re.finditer(rf"\b{re.escape(term.casefold())}\b", text.casefold()):
        before = text.casefold()[max(0, match.start() - 32) : match.start()]
        after = text.casefold()[match.end() : match.end() + 12]
        if re.search(
            r"(?:no|without|free\s+(?:of|from)|does\s+not\s+contain)\s+(?:[\w-]+\s+){0,2}$", before
        ):
            continue
        if re.match(r"\s*[- ]free\b", after):
            continue
        return True
    return False


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
            if item.evidence_type == "ocr_transcription":
                budget_has_uncomparable_items = True
                reasons.append(
                    "An OCR-read price is not independently text-verifiable against the "
                    "stated budget."
                )
                continue
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
    if request.other_preferences:
        reasons.append("Other preferences have not been independently verified.")
    confirmed = any(
        item.dietary_status == "confirmed" and item.evidence_type == "printed_text"
        for item in eligible
    )
    other_constraints_verified = not request.meal and not request.preferred_cuisine
    if (
        confirmed
        and budget_known
        and budget_match
        and other_constraints_verified
        and not request.allergies
        and not request.avoided_ingredients
        and not request.other_preferences
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
        or bool(request.other_preferences)
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
