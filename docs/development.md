# Development notes

Use Python 3.12 or 3.13 with `uv` in `backend/`; `pyproject.toml` holds bounded compatible dependency ranges and separates development tools. Use npm in `frontend/`. Keep dependency lockfiles committed once generated in an environment with registry access.

Run backend checks with `uv run pytest` and `uv run ruff check .`. Run frontend checks with `npm run lint`, `npm run typecheck`, `npm run test`, and `npm run build`. `backend/.env` and `frontend/.env.local` are local-only files; copy the adjacent examples and replace placeholders outside source control.

When adding a provider, define its interface in `app/integrations/` and keep provider-specific response normalization there. Put orchestration in `app/services/`; expose validated input/output contracts through `app/schemas/` and routes through `app/api/routes/`. Preserve citations and retrieval timestamps through every transformation.

## Validation environment note

The initial validation was run in a restricted Windows workspace. `uv sync --dev`, backend tests, backend linting, frontend linting, frontend type checking, frontend unit tests, and npm audit completed successfully. The backend tests passed when invoked with `.venv/Scripts/python.exe -m pytest`; this sandbox's temporary `uv run pytest` launcher failed to canonicalize its script path. The production build could not finish: the Next.js SWC compiler failed to canonicalize the workspace path with an access-denied error. Rerun `npm run build` in a normal local checkout. Vitest needed `TEMP` and `TMP` directed to a writable workspace directory in this sandbox; ordinary local Windows setups can use the documented `npm run test` command directly.
