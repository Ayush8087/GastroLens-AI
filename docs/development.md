# Development notes

Use Python 3.12 or 3.13 with `uv` in `backend/`; `pyproject.toml` holds bounded compatible dependency ranges and separates development tools. Use npm in `frontend/`. Keep dependency lockfiles committed once generated in an environment with registry access.

Run backend checks with `uv run pytest` and `uv run ruff check .`. Run frontend checks with `npm run lint`, `npm run typecheck`, `npm run test`, and `npm run build`. `backend/.env` and `frontend/.env.local` are local-only files; copy the adjacent examples and replace placeholders outside source control.

When adding a provider, define its interface in `app/integrations/` and keep provider-specific response normalization there. Put orchestration in `app/services/`; expose validated input/output contracts through `app/schemas/` and routes through `app/api/routes/`. Preserve citations and retrieval timestamps through every transformation.

## Validation environment note

The initial validation was run in a restricted Windows workspace. `uv sync --dev`, backend tests, backend linting, frontend linting, frontend type checking, frontend unit tests, and npm audit completed successfully. The backend tests passed when invoked with `.venv/Scripts/python.exe -m pytest`; this sandbox's temporary `uv run pytest` launcher failed to canonicalize its script path. The production build could not finish: the Next.js SWC compiler failed to canonicalize the workspace path with an access-denied error. Rerun `npm run build` in a normal local checkout. Vitest needed `TEMP` and `TMP` directed to a writable workspace directory in this sandbox; ordinary local Windows setups can use the documented `npm run test` command directly.

# Restaurant search API

## Configuration

Set `TAVILY_API_KEY` in `backend/.env` to enable live searches. Without it, the route returns HTTP 200 with no restaurants and a configuration warning. `APP_ENV`, `LOG_LEVEL`, `DATABASE_URL`, and `CORS_ORIGINS` retain the existing backend settings. Keep credentials in the backend environment; never use `NEXT_PUBLIC_` variables for provider keys.

## Request

`POST /api/v1/restaurants/search`

```json
{
  "city": "Barcelona",
  "meal": "lunch",
  "dietary_requirements": ["vegetarian"],
  "preferred_cuisine": "Catalan",
  "max_budget_per_person": 30,
  "currency": "EUR",
  "max_results": 10
}
```

`meal` accepts `breakfast`, `lunch`, or `dinner`; city defaults to Barcelona; dietary requirements default to vegetarian; budget and cuisine are optional; result count is bounded from 1 to 20. The budget is used to shape a query and is not independently checked against menu prices.

## Response example

Search results depend on live Tavily data and are never seeded. A representative response shape is:

```json
{
  "criteria": {"city": "Barcelona", "meal": "lunch", "dietary_requirements": ["vegetarian"], "preferred_cuisine": null, "max_budget_per_person": null, "currency": "EUR", "max_results": 10},
  "restaurants": [
    {
      "restaurant_name": "Name from a returned source title",
      "city_or_address": null,
      "official_website_url": null,
      "menu_url": null,
      "source_evidence": [{"url": "https://source.example/page", "title": "Provider title", "snippet": "Provider snippet", "source_type": "unclassified", "retrieved_at": "2026-01-01T12:00:00Z", "accessible": true, "http_status": 200, "note": null}],
      "retrieved_at": "2026-01-01T12:00:00Z",
      "verification_status": "partially_verified",
      "verification_evidence": ["Source returned HTTP 200: https://source.example/page"],
      "unknown_fields": ["city_or_address", "restaurant_identity", "vegetarian_suitability"],
      "dietary_suitability": "unconfirmed"
    }
  ],
  "warnings": []
}
```

The example is a schema illustration and contains no asserted restaurant data. `official_website_url` is only populated when a source's domain tokens and accessible page text match the discovered name, on the same host; this remains a candidate, not ownership proof. A discovered menu link is separate from successful access, shown on its source evidence item.

## Status, evidence, and failures

See [architecture](architecture.md#verification-and-provenance) for status definitions. `discovered` means no page was checked successfully; `partially_verified` means at least one source is accessible; `verified` means a name/domain-matching restaurant-site candidate is accessible and its page text contains the discovered name. None confirms vegetarian suitability. Each source records the Tavily title/snippet, normalized URL, retrieval time, source type, HTTP outcome, and access note. Provider missing-key, rate-limit, malformed-response, and outage cases return warnings and no fabricated search results.

Tests use mocked Tavily and HTTPX responses and require no API key or charge. Run `uv run pytest` and `uv run ruff check .` from `backend/`.
