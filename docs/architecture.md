# Architecture

## Request path

The Next.js client sends the user's query and optional constraints to `POST /api/v1/restaurants/search/stream`; API clients can use `POST /api/v1/restaurants/search` for JSON. FastAPI validates the Pydantic request. If configured, `GeminiResearchProvider` extracts structured constraints, then application code keeps only fields grounded in the original user text. A conservative phrase parser remains the fallback. `GooglePlacesProvider` supplies restaurant identity, address, place coordinates, Maps listing, website, business status, rating, review count, restaurant type, and provider price level when those fields are returned. Rating, review, type, and price-level fields can require a higher Google Places billing tier. Browser coordinates are used only after the user grants permission. No location, currency, cuisine, or dietary defaults are inserted.

When Google Places is missing, unavailable, or returns no listings, Tavily can return web search leads. These leads have no Google address, ratings, or hours and are labeled as unverified. For Google candidates, Tavily finds potential restaurant and menu sources. The service keeps provider identity separate, validates URL syntax, and passes pages through `SourceVerifier`. If no menu URL is already available, `MenuResearchService` inspects safe official-site links. Retrieval enforces public-address and redirect checks, timeouts, and response-size limits. HTML/PDF text is parsed locally. Gemini may identify structured menu evidence or OCR a bounded scanned PDF; quoted text must match the retrieved representation, while OCR-derived lines remain unverified and cannot confirm dietary labels or budget eligibility.

`GeminiResearchProvider` runs only when `GEMINI_API_KEY` is configured. Its translations are separate name/description fields; they never alter original text, prices, dietary status, or evidence. Failed translation leaves the original visible. `GET /health/providers` reports configuration only and makes no external calls.

Dish status and restaurant ordering are deterministic. An explicit dietary label can confirm only when found on a verified official restaurant domain. Negated labels and literal allergy/avoid conflicts contradict a dish. Absence stays unknown; an absent allergen never establishes allergy safety. Each dish carries its own `match_status` and `match_reasons`: confirmed matches, partial matches, items needing checking, or excluded items. Budget checks use printed prices only, require a matching explicit currency, and do not use currency conversion. OCR prices are suggestions and cannot satisfy or exclude a hard budget. An exact quote can support an unpriced dish candidate, but it remains unpriced and cannot pass a budget check. Exact/partial/uncertain/excluded restaurant statuses and evidence reasons accompany the score; provider order is tie-broken deterministically by name and place ID.

The fixed score tiers are 90 (evidence-backed exact), 60 (partial), 35 (uncertain), and 0 (excluded). Exact status requires explicit dietary text, no unresolved meal or cuisine criterion, and a satisfied budget if one was specified. A dish is excluded for a literal allergy/avoid conflict; a restaurant is excluded by price only when every comparable extracted price exceeds the stated budget. Mixed or unknown currencies do not create an exclusion.

## Provider coverage

Google Places Text Search is the preferred structured listing provider. Its regional coverage and quality vary; an empty response is not proof that no restaurant exists. Ratings, review counts, restaurant type, and price level are shown only when Google returns them. Review text and opening hours are not currently retrieved, so meal-time suitability is reported as unverified. Tavily fallback is best-effort web search and cannot supply structured listing details or complete geographic coverage. The API exposes coverage notes and provider warnings. `GET /health/providers` never tests credentials against the network. Credentials stay on the backend.

## URL safety and provenance

Only HTTP and HTTPS URLs are accepted; credentials, localhost, private/non-global addresses, unsafe redirects, excessive redirects, long waits, and large menu responses are rejected. Redirect destinations are checked again. DNS lookup and the eventual HTTP connection are separate, leaving a DNS rebinding risk; outbound network policy or DNS-pinned transport is recommended for production.

Evidence items retain source URL, title/snippet, retrieval timestamp, accessibility, status, and notes. Dish evidence points to the fetched menu page and exact printed line. Translations are clearly separate from source evidence. An accessible page/name match is a consistency check; it does not prove ownership, restaurant operation, opening hours, or dietary safety.

## Boundaries

- `schemas/`: API request and response validation.
- `api/routes/`: HTTP endpoint and dependency wiring.
- `integrations/`: replaceable Google Places, Tavily search, and Gemini research adapters.
- `services/`: discovery orchestration, source verification, menu retrieval/extraction, and deterministic matching.
- `tests/`: fixtures and mocked provider/HTTP workflows; no provider keys or paid calls required.

PostgreSQL dependencies remain unused. Searches are synchronous and not persisted. See [limitations](limitations.md) for extraction, freshness, and dietary boundaries.
