# GastroLens-AI

Production-minded monorepo foundation for an AI restaurant research agent for European travellers. The initial product scope is Barcelona and vegetarian-friendly meals. Restaurant discovery and AI workflows are intentionally not implemented yet.

## Repository layout

```text
frontend/                 Next.js App Router (TypeScript, Tailwind)
backend/                  FastAPI service and Python tests
  app/api/                 HTTP routes
  app/core/                Settings, validation, logging
  app/db/                  SQLAlchemy base and future persistence
  app/integrations/        Replaceable external provider boundaries
  app/schemas/             API request/response schemas
  app/services/            Application use cases (future)
  tests/                   Pytest coverage
docs/                      Architecture, assumptions, limitations
```

## Prerequisites

- Node.js 20.9 or newer and npm.
- Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).
- PostgreSQL for future persistence. The health check does not require a running database.

## Configure

Copy `backend/.env.example` to `backend/.env` and `frontend/.env.example` to `frontend/.env.local` if needed. The examples contain placeholders only. Keep real credentials out of Git. `OPENAI_API_KEY` and `TAVILY_API_KEY` are backend-only settings and are never exposed to the browser.

## Run locally

Backend, from `backend/`:

```bash
uv sync --dev
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The health endpoint is `GET http://127.0.0.1:8000/health`; OpenAPI docs are at `/docs` in development.

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

This repository contains the project foundation only. Restaurant discovery, identity verification, menu and review extraction, evidence-backed ranking, and citation APIs remain to be designed and implemented. The health endpoint checks process liveness only; it does not check PostgreSQL or provider availability. See [architecture](docs/architecture.md), [assumptions](docs/assumptions.md), [limitations](docs/limitations.md), and [development](docs/development.md) for decisions and validation notes.
