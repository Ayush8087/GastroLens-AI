# Architecture

## Runtime boundaries

- `frontend/` is a Next.js App Router application intended for Vercel. It owns presentation and user interaction. Provider credentials stay in the backend.
- `backend/` is a FastAPI ASGI application intended for a Python-compatible host. Routes validate transport concerns; schemas define API contracts; services will hold use cases; integrations will adapt external providers; `db/` will own SQLAlchemy persistence.
- PostgreSQL is the planned system of record. Alembic migrations belong to the backend deployment lifecycle. No tables or migrations are introduced until domain requirements are designed.
- `docs/` records decisions and operating assumptions.

## Discovery request path

`POST /api/v1/restaurants/search` validates the user criteria with Pydantic, calls the `SearchProvider` interface for bounded targeted queries, normalizes and deduplicates search sources, then asks `SourceVerifier` to check each discovered HTTP(S) page. `TavilySearchProvider` is the current adapter and sends requests server-side using `TAVILY_API_KEY`. A Tavily outage returns no invented candidates and adds a warning. Search and verification have bounded timeouts; transient Tavily network errors and rate limiting receive a small bounded retry budget.

Search result URLs are normalized and deduplicated exactly. Restaurant identity is intentionally not merged across different page URLs because address-level branch identity is not reliably present in search snippets. This can leave duplicate branches in the result set rather than merging two locations incorrectly. Menu URLs are discoveries; their `source_evidence.accessible` field reports whether the corresponding URL could be fetched.

The verifier accepts only HTTP and HTTPS URLs, rejects user information, localhost and non-public IP addresses, disables automatic redirects, revalidates each redirect target, and limits redirect count and response bytes. DNS is resolved before each request and every resolved address must be public. Tavily and page requests are backend-only; API keys are not returned to clients or written to logs.

## Verification and provenance

- `discovered`: search returned a candidate, but no source page was successfully checked.
- `partially_verified`: at least one source returned a successful HTTP response, but the available evidence does not meet the restaurant-site identity check.
- `verified`: a source classified as a restaurant-site candidate from a name/domain match is accessible and its bounded page text contains the discovered restaurant name. This is a source and name consistency check; it does not prove domain ownership, current operation, address, or dietary suitability.

Every source evidence item carries the returned URL, provider title/snippet, retrieval timestamp, source classification, accessibility, HTTP status, and a failure note where relevant. Unknown restaurant identity, address, and vegetarian suitability remain visible. Search snippets alone never confirm dietary suitability. A future menu extraction step must attach its own source and item-level evidence before dietary claims can be made.

## Future evidence flow

The discovery service preserves source references and retrieval timestamps, and records uncertainty when candidate identity cannot be resolved. Future HTML/PDF extraction should attach source URLs, retrieval times, and source locations to each extracted menu item. Review analysis and ranking should retain the exact evidence used, separate positive and negative signals, and avoid claims unsupported by sources. Provider interfaces keep Tavily and OpenAI replaceable; application services must not depend directly on vendor SDKs.

## Operational boundaries

Configuration is environment-driven and validated on startup. CORS is an explicit origin allowlist. Logs are structured JSON and must not contain secrets, prompts with personal data, or provider credentials. Liveness (`/health`) intentionally does not claim database or provider readiness. Add separate readiness checks when those dependencies become part of the request path.

## Deployment

Vercel builds from `frontend/`. The backend is a separate ASGI deployment configured with its own secrets and CORS allowlist. Use a managed PostgreSQL service compatible with the backend host when persistence is added. Do not expose OpenAI or Tavily credentials in frontend environment variables.
