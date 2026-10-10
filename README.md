# GastroLens-AI

GastroLens researches restaurants against user-provided locations and preferences, then returns source-linked menu findings with uncertainty visible. Locations, currencies, cuisines, and dietary preferences are not hardcoded. Coverage depends on Google Places and Tavily availability in the requested area.

## Current workflow

- Natural-language requests are interpreted by Gemini when configured, then validated against the original text. A conservative phrase parser remains as a fallback.
- Google Places is the structured discovery provider. Tavily provides a lower-confidence restaurant lead fallback and finds candidate restaurant/menu sources.
- Menu links are searched on restaurant websites and retrieved only after HTTP(S), public-address, redirect, timeout, and response-size checks.
- HTML and text PDFs are parsed locally. Gemini can return structured exact source quotes; each quoted item is checked against retrieved text and the printed price is parsed locally. Scanned PDF OCR is attempted through Gemini when text extraction yields no priced items.
- Gemini translations are separate fields; the original name, description, price, currency, and evidence remain unchanged.
- Deterministic Python rules evaluate explicit menu labels, literal avoid conflicts, printed prices, currencies, and location distance. Unknown allergy or dietary status is never treated as safe.
- The frontend streams actual backend progress, supports browser geolocation, shows dish evidence and links, and includes loading, retry, cancellation, warning, and empty states.

Review analysis, reservations, persistence, currency conversion, and complete worldwide coverage are not implemented. Scanned PDF vision extraction and Gemini outputs require a configured key and have not been live-tested in this workspace. OCR transcripts are surfaced as unverified suggestions and cannot qualify dietary or hard budget matches.

## Requirements

- Node.js 20.9+ and npm
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- `GOOGLE_PLACES_API_KEY` for structured discovery and coordinate-based search
- `TAVILY_API_KEY` for menu/source discovery and web-search fallback
- `GEMINI_API_KEY` for natural-language interpretation, structured extraction, scanned PDF fallback, and translation

Enable Places API (New) in Google Cloud. Create a Tavily key in [Tavily](https://app.tavily.com/home). Create a Gemini API key in [Google AI Studio](https://aistudio.google.com/app/apikey). Usage may incur provider charges or be limited by quota; check each provider's current [Google Places pricing](https://mapsplatform.google.com/pricing/), [Tavily plans](https://tavily.com/#pricing), and [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing). Google Places is preferred. Tavily fallback results do not include structured Google ratings, hours, or verified addresses, and do not provide complete geographic coverage. If credentials are absent, the app does not fabricate results. Keys remain on the backend.

## Configure

From the repository root in Windows PowerShell:

```powershell
Copy-Item backend/.env.example backend/.env
Copy-Item frontend/.env.example frontend/.env.local
```

Add the provider values to `backend/.env`. The supported names are `GOOGLE_PLACES_API_KEY`, `TAVILY_API_KEY`, `GEMINI_API_KEY`, and optional `GEMINI_MODEL` (default `gemini-3.8-flash`). `APP_ENV`, `LOG_LEVEL`, `DATABASE_URL`, and `CORS_ORIGINS` are backend settings. Set `CORS_ORIGINS` to the exact frontend origin in deployment. `.env` files are Git-ignored.

For local development, `frontend/.env.example` can be copied to `frontend/.env.local`. It points to `http://localhost:8000`; the variable contains no secrets.

## Run locally

Start the backend from `backend/`:

```bash
uv sync --dev
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Start the frontend from `frontend/`:

```bash
npm ci
npm run dev
```

Open `http://localhost:3000`. The API liveness endpoint is `/health`; development OpenAPI docs are at `/docs`.
Check local key configuration without making provider requests at `http://localhost:8000/health/providers` or with `Invoke-RestMethod http://localhost:8000/health/providers`. This endpoint reports only whether a key is configured; it does not validate credentials or spend API credits.

## Search API

The frontend uses `POST /api/v1/restaurants/search/stream` for server-sent progress and a final result event. `POST /api/v1/restaurants/search` returns the same response as JSON for API clients.

```json
{
  "query": "A relaxed dinner with vegetarian options in Kyoto",
  "location": "Kyoto",
  "search_radius_meters": 3000,
  "meal": "dinner",
  "dietary_requirements": ["vegetarian"],
  "avoided_ingredients": [],
  "allergies": [],
  "preferred_cuisine": null,
  "max_budget_per_person": null,
  "currency": null,
  "target_language": "English",
  "other_preferences": ["quiet", "outdoor seating"],
  "max_results": 10
}
```

All constraints except the result limit are optional. When Gemini is unavailable, common meal, diet, location, radius, and budget expressions are parsed conservatively. A location is required unless browser coordinates are supplied. Geolocation uses explicit browser permission and a 5 km Places bias by default. Text-only radius values are hints and cannot enforce exact distance. Response criteria include validated filters; provider warnings and unknown fields explain missing or unverified information.

### Status meanings

- `discovered`: returned by the listing provider; no confirming restaurant website evidence was established.
- `partially_verified`: at least one source was accessible, but restaurant identity or ownership is incomplete.
- `verified`: an accessible restaurant-site candidate contains the provider-supplied restaurant name. This is a consistency check, not proof of ownership, current operation, or dietary suitability.
- `exact_match`, `partial_match`, `uncertain`, `excluded`: deterministic menu-evidence assessment. A requested allergy or avoided ingredient is never treated as safe merely because a menu line omits it.

Scores use fixed evidence tiers: 90 for an explicitly labeled dietary match with a satisfied requested budget and no unresolved meal, cuisine, allergy, or avoid constraint; 60 for partial evidence; 35 when important facts remain unknown; and 0 for an excluded candidate. Exclusion requires explicit conflicting menu text or comparable printed prices that all exceed the budget. Results sort by status, score, name, then provider place ID.

Every extracted dish retains its source URL, exact printed line, and retrieval timestamp. Gemini extraction is accepted only when its proposed quote exactly appears in the retrieved text and normal code can parse a price from it. Translation is separate and never changes source evidence or deterministic matching fields. An explicit dietary label is only treated as confirmed when the menu is on a verified official restaurant domain. Allergy safety remains unknown unless an allergen appears in the line, in which case the item is marked as a conflict. Printed price currency is not guessed from an ambiguous `$` sign. Budget checks require a matching explicit currency; there is no automatic currency conversion.

## Checks

From `backend/`: `uv run pytest` and `uv run ruff check app tests`.

From `frontend/`: `npm run lint`, `npm run typecheck`, and `npm run test`. The production build can be checked with `npm run build`.

## Deployment

Deploy `frontend/` from Vercel and deploy `backend/` as a Python ASGI service, for example with `uvicorn app.main:app`. Configure server-side provider keys and explicit CORS origins on the backend. Provider API usage may incur charges under the provider's account and terms.
