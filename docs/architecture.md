# Architecture

## Runtime boundaries

- `frontend/` is a Next.js App Router application intended for Vercel. It owns presentation and user interaction. Provider credentials stay in the backend.
- `backend/` is a FastAPI ASGI application intended for a Python-compatible host. Routes validate transport concerns; schemas define API contracts; services will hold use cases; integrations will adapt external providers; `db/` will own SQLAlchemy persistence.
- PostgreSQL is the planned system of record. Alembic migrations belong to the backend deployment lifecycle. No tables or migrations are introduced until domain requirements are designed.
- `docs/` records decisions and operating assumptions.

## Future evidence flow

Discovery should preserve raw provider references and retrieval timestamps. Identity resolution and deduplication should retain candidate provenance and record uncertainty. HTML/PDF extraction should attach source URLs, retrieval times, and source locations to each extracted menu item. Review analysis and ranking should retain the exact evidence used, separate positive and negative signals, and avoid claims unsupported by sources. Provider interfaces keep Tavily and OpenAI replaceable; application services must not depend directly on vendor SDKs.

## Operational boundaries

Configuration is environment-driven and validated on startup. CORS is an explicit origin allowlist. Logs are structured JSON and must not contain secrets, prompts with personal data, or provider credentials. Liveness (`/health`) intentionally does not claim database or provider readiness. Add separate readiness checks when those dependencies become part of the request path.

## Deployment

Vercel builds from `frontend/`. The backend is a separate ASGI deployment configured with its own secrets and CORS allowlist. Use a managed PostgreSQL service compatible with the backend host when persistence is added. Do not expose OpenAI or Tavily credentials in frontend environment variables.
