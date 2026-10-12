# Development

## Local setup

Use Python 3.12 or 3.13 with `uv` for `backend/`, and Node.js 20.9+ with npm for `frontend/`. Copy `backend/.env.example` to `backend/.env`; configure `GOOGLE_PLACES_API_KEY`, `TAVILY_API_KEY`, and `GEMINI_API_KEY` for the complete research pipeline. Keep these credentials server-side. Set explicit `CORS_ORIGINS` for the frontend URL.

Run the API from `backend/` with `uv sync --dev` followed by `uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`. Run the frontend from `frontend/` with `npm ci` then `npm run dev`. The frontend base URL is configurable through `NEXT_PUBLIC_API_BASE_URL`; it is not a provider key.

## API contract

`POST /api/v1/restaurants/search` accepts `query`, `location`, `latitude`, `longitude`, `search_radius_meters`, `meal`, `dietary_requirements`, `avoided_ingredients`, `allergies`, `preferred_cuisine` (legacy single value), `preferred_cuisines`, `max_budget_per_person`, `currency`, `target_language`, `party_size`, `other_preferences`, and `max_results`. Meal values are `breakfast`, `brunch`, `lunch`, `supper`, and `dinner`. The location is required unless coordinates are supplied. Search supports user-provided locations subject to Google Places and Tavily coverage. The location field accepts free text; provider-backed autocomplete is not currently integrated. Text radius is only a search hint; browser coordinates enable Places location bias and measured-distance filtering. The UI uses the companion `POST /api/v1/restaurants/search/stream` endpoint, which emits `progress`, `result`, or `error` server-sent events and can be canceled by closing the request.

The response has `criteria`, `restaurants`, `warnings`, and `provider_coverage`. Each candidate includes identity and source fields, `verification_status`, `match_status`, `score`, `match_reasons`, `menu_items`, and `unknown_fields`. Menu items carry original and optional translated names/descriptions, printed price/currency, source quote and URL, retrieval time, extraction confidence, conservative dietary/allergen status, and deterministic per-dish `match_status` / `match_reasons`. Grounded unpriced menu entries may be shown as candidates but cannot satisfy a budget. `GET /health/providers` reports configured keys only and never makes live calls.

## Verification commands

From `backend/`:

```bash
uv run pytest
uv run ruff check app tests
```

From `frontend/`:

```bash
npm run lint
npm run typecheck
npm run test
npm run build
```

Tests mock provider and HTTP responses. They do not require keys or call paid services. For a live manual search, configure provider credentials first; review usage and terms at the providers.
