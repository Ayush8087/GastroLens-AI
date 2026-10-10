# Architecture

## Request path

The Next.js client sends the user's query and optional constraints to `POST /api/v1/restaurants/search/stream`; API clients can use `POST /api/v1/restaurants/search` for JSON. FastAPI validates the Pydantic request, conservatively extracts obvious meal/diet/location/budget phrases, then calls the location-aware `PlaceSearchProvider`. The stream emits actual backend stages and a final result, and request cancellation propagates to in-flight research. `GooglePlacesProvider` supplies restaurant identity, address, listing URL, website, and business status. No location or preference defaults are inserted.

For each returned place, the discovery service uses Tavily as an optional source-finding integration. Its results are leads only. The service keeps Google Places identity/address separate, validates URL syntax, and passes discovered source pages through `SourceVerifier`. A menu URL is fetched by `MenuResearchService` only after public-IP and redirect checks, timeout, and response-size limits. HTML text and PDF text are parsed for clearly printed dish/price lines. Every item preserves the exact line and final source URL.

`OpenAITranslationProvider` runs only when a target language is requested and `OPENAI_API_KEY` exists. It receives menu text only, returns translated strings in a separate field, and is not allowed to modify original text, prices, dietary status, or evidence. Failed translation leaves the original visible.

Dish status and restaurant ordering are deterministic. Explicit menu labels can confirm a requested diet; literal occurrence of an allergy/avoid term contradicts a dish. Absence is unknown. Budget checks use only extracted prices with a matching explicit currency. Exact/partial/uncertain/excluded statuses and short reasons accompany a score; provider order is tie-broken deterministically by name and place ID.

The fixed score tiers are 90 (evidence-backed exact), 60 (partial), 35 (uncertain), and 0 (excluded). Exact status requires explicit dietary text, no unresolved meal or cuisine criterion, and a satisfied budget if one was specified. A dish is excluded for a literal allergy/avoid conflict; a restaurant is excluded by price only when every comparable extracted price exceeds the stated budget. Mixed or unknown currencies do not create an exclusion.

## Provider coverage

Google Places Text Search is the current restaurant discovery provider. Its regional coverage and quality vary; an empty response is not proof that no restaurant exists. The API exposes a coverage note and preserves provider outages as warnings. Tavily and OpenAI enrich results but are optional; only Google Places is required for discovery. Credentials stay on the backend.

## URL safety and provenance

Only HTTP and HTTPS URLs are accepted; credentials, localhost, private/non-global addresses, unsafe redirects, excessive redirects, long waits, and large menu responses are rejected. Redirect destinations are checked again. DNS lookup and the eventual HTTP connection are separate, leaving a DNS rebinding risk; outbound network policy or DNS-pinned transport is recommended for production.

Evidence items retain source URL, title/snippet, retrieval timestamp, accessibility, status, and notes. Dish evidence points to the fetched menu page and exact printed line. Translations are clearly separate from source evidence. An accessible page/name match is a consistency check; it does not prove ownership, restaurant operation, opening hours, or dietary safety.

## Boundaries

- `schemas/`: API request and response validation.
- `api/routes/`: HTTP endpoint and dependency wiring.
- `integrations/`: replaceable Google Places, Tavily search, and OpenAI translation adapters.
- `services/`: discovery orchestration, source verification, menu retrieval/extraction, and deterministic matching.
- `tests/`: fixtures and mocked provider/HTTP workflows; no provider keys or paid calls required.

PostgreSQL dependencies remain unused. Searches are synchronous and not persisted. See [limitations](limitations.md) for extraction, freshness, and dietary boundaries.
