# Development

## Local setup

Use Python 3.12 or 3.13 with `uv` for `backend/`, and Node.js 20.9+ with npm for `frontend/`. Copy `backend/.env.example` to `backend/.env`; set `GOOGLE_PLACES_API_KEY` for restaurant discovery, `TAVILY_API_KEY` for menu/source lookup, and `OPENAI_API_KEY` only for translation. Keep these credentials server-side. Set explicit `CORS_ORIGINS` for the frontend URL.

Run the API from `backend/` with `uv sync --dev` followed by `uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`. Run the frontend from `frontend/` with `npm ci` then `npm run dev`. The frontend base URL is configurable through `NEXT_PUBLIC_API_BASE_URL`; it is not a provider key.

## API contract

`POST /api/v1/restaurants/search` accepts `query`, `location`, `meal`, `dietary_requirements`, `avoided_ingredients`, `allergies`, `preferred_cuisine`, `max_budget_per_person`, `currency`, `target_language`, and `max_results`. All constraints are optional. The location must be explicit or recognized in query text. Search supports any user-specified location subject to Google Places coverage. The UI uses the companion `POST /api/v1/restaurants/search/stream` endpoint, which emits `progress`, `result`, or `error` server-sent events and can be canceled by closing the request.

The response has `criteria`, `restaurants`, `warnings`, and `provider_coverage`. Each candidate includes identity and source fields, `verification_status`, `match_status`, `score`, `match_reasons`, `menu_items`, and `unknown_fields`. Menu items carry original text, optional translation, printed price/currency, exact evidence, source URL, and conservative dietary status.

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
