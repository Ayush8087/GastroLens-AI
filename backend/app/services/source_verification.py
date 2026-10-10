import asyncio
import ipaddress
import logging
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from app.schemas.restaurant_search import RestaurantCandidate, SourceEvidence

logger = logging.getLogger(__name__)
MAX_REDIRECTS = 3


def normalize_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username or parsed.password:
            return None
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        formatted_host = f"[{host}]" if ":" in host else host
        port = parsed.port
        netloc = (
            formatted_host
            if port is None or (parsed.scheme.lower(), port) in {("http", 80), ("https", 443)}
            else f"{formatted_host}:{port}"
        )
        path = parsed.path or "/"
        return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))
    except (ValueError, UnicodeError):
        return None


class SourceVerifier:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        timeout: float = 5.0,
        safety_check: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self.client = client
        self.timeout = timeout
        self.safety_check = safety_check or _is_public_http_url

    async def verify(self, candidate: RestaurantCandidate) -> RestaurantCandidate:
        checked: list[SourceEvidence] = []
        confirmations: list[str] = []
        accessible_restaurant_site = False
        for source in candidate.source_evidence:
            normalized = normalize_url(source.url)
            if normalized is None:
                checked.append(
                    source.model_copy(
                        update={"accessible": False, "note": "Invalid or unsupported URL."}
                    )
                )
                continue
            status, final_url, note, identity_match = await self._check_url(
                normalized, candidate.restaurant_name
            )
            source_type = source.source_type
            checked.append(
                source.model_copy(
                    update={
                        "url": normalized,
                        "final_url": final_url,
                        "accessible": status is not None
                        and 200 <= status < 300
                        and final_url is not None,
                        "http_status": status,
                        "source_type": source_type,
                        "note": note,
                    }
                )
            )
            if status is not None and 200 <= status < 300 and final_url is not None:
                confirmations.append(f"Source returned HTTP {status}: {normalized}")
                same_host = final_url is not None and _same_host(normalized, final_url)
                if source_type == "restaurant_site_candidate" and identity_match and same_host:
                    accessible_restaurant_site = True
        candidate.source_evidence = checked
        candidate.verification_evidence = confirmations
        candidate.verification_status = "partially_verified" if confirmations else "discovered"
        if accessible_restaurant_site and candidate.restaurant_name:
            candidate.verification_status = "verified"
            candidate.official_website_url = next(
                (
                    source.url
                    for source in checked
                    if source.source_type == "restaurant_site_candidate"
                    and source.accessible
                    and source.final_url
                    and _same_host(source.url, source.final_url)
                ),
                None,
            )
            candidate.verification_evidence.append(
                "An accessible restaurant-site candidate matches the discovered name. "
                "Ownership is not independently proven."
            )
        if candidate.official_website_url is not None:
            candidate.unknown_fields = [
                field for field in candidate.unknown_fields if field != "official_website_url"
            ]
        candidate.dietary_suitability = "unconfirmed"
        return candidate

    async def _check_url(
        self, url: str, expected_name: str | None
    ) -> tuple[int | None, str | None, str | None, bool]:
        current = url
        owns_client = self.client is None
        client = (
            self.client
            if self.client is not None
            else httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=False,
                trust_env=False,
                headers={"User-Agent": "GastroLensResearch/0.1 (+source verification)"},
            )
        )
        try:
            for _ in range(MAX_REDIRECTS + 1):
                if not await self.safety_check(current):
                    return None, None, "Blocked unsafe host or redirect target.", False
                try:
                    async with client.stream("GET", current, follow_redirects=False) as response:
                        status = response.status_code
                        if status in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                return status, current, "Redirect has no location.", False
                            next_url = normalize_url(urljoin(current, location))
                            if next_url is None or not await self.safety_check(next_url):
                                return status, None, "Blocked unsafe redirect target.", False
                            current = next_url
                            continue
                        if not 200 <= status < 400:
                            return status, current, "Source returned an unsuccessful status.", False
                        content = bytearray()
                        async for chunk in response.aiter_bytes():
                            content.extend(chunk[: max(0, 65536 - len(content))])
                            if len(content) >= 65536:
                                break
                        return (
                            status,
                            current,
                            None,
                            _page_mentions_name(bytes(content), expected_name),
                        )
                except (TimeoutError, httpx.HTTPError, OSError) as exc:
                    logger.info(
                        "source_verification_failed",
                        extra={
                            "host": urlsplit(current).hostname,
                            "error_type": type(exc).__name__,
                        },
                    )
                    return None, None, "Source could not be accessed.", False
            return None, None, "Redirect limit exceeded.", False
        finally:
            if owns_client:
                await client.aclose()


async def _is_public_http_url(url: str) -> bool:
    normalized = normalize_url(url)
    if normalized is None:
        return False
    host = urlsplit(normalized).hostname
    if (
        host is None
        or host.lower() in {"localhost", "localhost.localdomain"}
        or host.lower().endswith(".localhost")
    ):
        return False
    try:
        literal = ipaddress.ip_address(host)
        return literal.is_global
    except ValueError:
        pass
    try:
        records = await asyncio.to_thread(socket.getaddrinfo, host, None, type=socket.SOCK_STREAM)
    except (OSError, socket.gaierror):
        return False
    addresses = {record[4][0] for record in records}
    return bool(addresses) and all(_is_global_ip(address) for address in addresses)


def _is_global_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def _same_host(first: str, second: str) -> bool:
    first_host = (urlsplit(first).hostname or "").removeprefix("www.").lower()
    second_host = (urlsplit(second).hostname or "").removeprefix("www.").lower()
    return bool(first_host) and first_host == second_host


def _page_mentions_name(content: bytes, name: str | None) -> bool:
    if not name or not content:
        return False
    try:
        text = BeautifulSoup(content, "html.parser").get_text(" ", strip=True)
    except (UnicodeDecodeError, ValueError):
        return False
    return name.casefold() in text.casefold()
