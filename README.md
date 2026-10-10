# GastroLens-AI

Production-minded monorepo for an AI restaurant research agent for European travellers. The initial scope is restaurant discovery in Barcelona, with vegetarian as the default dietary requirement. The backend search feature uses Tavily and retains source evidence and uncertainty; menu parsing, review analysis, ranking, and the frontend workflow remain future work.

## Repository layout

```text
frontend/                 Next.js App Router (TypeScript, Tailwind)
backend/                  FastAPI service and Python tests
  app/api/                 HTTP routes
  app/core/                Settings, validation, logging
  app/db/                  SQLAlchemy base and future persistence
  app/integrations/        Replaceable external provider boundaries
  app/schemas/             Validated API request/response schemas
  app/services/            Discovery use case and source verification
  tests/                   Pytest coverage
docs/                      Architecture, assumptions, limitations
```

## Prerequisites

- Node.js 20.9 or newer and npm.
- Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).
- PostgreSQL for future persistence. The health check does not require a running database.

## Configure

Copy `backend/.env.example` to `backend/.env` and `frontend/.env.example` to `frontend/.env.local` if needed. The examples contain placeholders only. Keep real credentials out of Git. `OPENAI_API_KEY` and `TAVILY_API_KEY` are backend-only settings and are never exposed to the browser.

Restaurant search requires `TAVILY_API_KEY`. Other relevant backend settings are `APP_ENV`, `LOG_LEVEL`, `DATABASE_URL`, and `CORS_ORIGINS`. Search returns an empty restaurant list with a warning if Tavily is not configured or unavailable; it never substitutes sample results.

## Run locally

Backend, from `backend/`:

```bash
uv sync --dev
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The health endpoint is `GET http://127.0.0.1:8000/health`; OpenAPI docs are at `/docs` in development.

Search restaurants with `POST http://127.0.0.1:8000/api/v1/restaurants/search`:

```json
{
  "city": "Barcelona",
  "meal": "dinner",
  "dietary_requirements": ["vegetarian"],
  "preferred_cuisine": "Catalan",
  "max_budget_per_person": 35,
  "currency": "EUR",
  "max_results": 8
}
```

The response contains `criteria`, `restaurants`, and `warnings`. Each restaurant includes available identity fields, source evidence with retrieval timestamps and accessibility results, a verification status, explicit unknown fields, and `dietary_suitability: "unconfirmed"`. For the response model and failure behavior, see [development documentation](docs/development.md).

Frontend, from `frontend/`:

```bash
npm ci
npm run dev
```

Visit `http://localhost:3000`. `NEXT_PUBLIC_API_BASE_URL` is provided as a placeholder for future browser calls to the backend. Never put provider secrets in a `NEXT_PUBLIC_` variable.

## Checks

```bash
# backend (from backend/)
uv run pytest
uv run ruff check .

# frontend (from frontend/)
npm run lint
npm run typecheck
npm run test
npm run build
```

## Deployment

Set `frontend/` as the Vercel project root. Deploy `backend/` as a Python ASGI application on a Python-compatible host using `uvicorn app.main:app`. Configure backend environment variables and an explicit production `CORS_ORIGINS` allowlist. Provision PostgreSQL when database-backed features are introduced.

## Scope and known limitations

The first discovery and source-verification API is implemented. It does not parse menus, confirm vegetarian suitability, analyze reviews, rank restaurants, or persist results. Source accessibility and name matching are limited evidence, not proof of business ownership or current restaurant operations. The health endpoint checks process liveness only; it does not check PostgreSQL or provider availability. See [architecture](docs/architecture.md), [assumptions](docs/assumptions.md), [limitations](docs/limitations.md), and [development](docs/development.md).
