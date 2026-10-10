# GastroLens-AI

GastroLens researches real restaurants against user-specified needs and returns source-linked findings with uncertainty visible. Locations, cuisines, diets, and currencies are optional user inputs; no destination or dietary preference is assumed. Results depend on the configured provider's geographic coverage and accuracy.

## What works in this slice

- Natural-language search text plus optional location, meal, cuisine, dietary terms, avoided ingredients, allergies, budget, currency, and translation language.
- Restaurant discovery from Google Places, including provider-supplied name, address, Maps listing, and business status.
- Tavily source discovery for relevant restaurant/menu pages, and safe URL checking before menu retrieval.
- Text extraction from HTML pages and text-based PDFs, with source URL and exact printed line retained for priced dishes.
- Conservative, deterministic dish and restaurant statuses. Explicit menu labels can confirm a requested diet; literal avoid/allergy terms can contradict it. Missing evidence stays uncertain.
- Optional menu translation through OpenAI. Original menu text remains alongside translations.
- Responsive search UI connected to the API, with loading, warnings, empty results, retry, and provider configuration messages.

Scanned PDFs are not OCR processed. The current menu extractor focuses on clear lines with printed prices and may miss complex menu layouts. Availability and provider status are snapshots; they do not guarantee a table or current operation. Review analysis and ranking from reviews are not implemented.

## Requirements

- Node.js 20.9+ and npm
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- A Google Places API key with Places API (New) enabled for structured restaurant discovery (recommended)
- A Tavily API key for menu/source discovery and best-effort discovery fallback
- An OpenAI API key only when requesting menu translation

Google Places Text Search is the preferred discovery provider; enable Places API (New) in the Google Cloud project. If Google Places is missing or unavailable, Tavily can return web search leads. Those leads have no structured address, ratings, or hours and remain unverified; Tavily does not promise complete geographic coverage. If both providers are unconfigured, search returns an empty result with configuration warnings. Tavily also locates candidate official sites and menu pages. OpenAI is only used for optional translation. All keys remain server-side. Provider coverage varies by location; there is no global completeness guarantee. Google documents this endpoint as a POST to `places.googleapis.com/v1/places:searchText` with a required field mask ([Text Search API](https://developers.google.com/maps/documentation/places/web-service/text-search)).

## Configure

Copy `backend/.env.example` to `backend/.env`. Fill the provider keys you intend to use. Keep `OPENAI_API_KEY`, `TAVILY_API_KEY`, and `GOOGLE_PLACES_API_KEY` server-side only. `APP_ENV`, `LOG_LEVEL`, `DATABASE_URL`, and `CORS_ORIGINS` are also backend settings. Set `CORS_ORIGINS` to the exact frontend origin in deployment.

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

## Search API

The frontend uses `POST /api/v1/restaurants/search/stream` for server-sent progress and a final result event. `POST /api/v1/restaurants/search` returns the same response as JSON for API clients.

```json
{
  "query": "A relaxed dinner with vegetarian options in Kyoto",
  "location": "Kyoto",
  "meal": "dinner",
  "dietary_requirements": ["vegetarian"],
  "avoided_ingredients": [],
  "allergies": [],
  "preferred_cuisine": null,
  "max_budget_per_person": null,
  "currency": null,
  "target_language": "English",
  "max_results": 10
}
```

All constraints except the result limit are optional. Obvious meal/diet/location phrases are extracted conservatively from `query`; if no location is found, the response asks for one. The response contains criteria, restaurants, provider warnings, coverage notes, source evidence, verification and match statuses, printed menu evidence, and unknown fields. A missing provider key returns no fabricated results.

### Status meanings

- `discovered`: returned by the listing provider; no confirming restaurant website evidence was established.
- `partially_verified`: at least one source was accessible, but restaurant identity or ownership is incomplete.
- `verified`: the source page is accessible and its text matches the provider-supplied restaurant name. This does not prove ownership, current operation, or dietary suitability.
- `exact_match`, `partial_match`, `uncertain`, `excluded`: deterministic menu-evidence assessment. A requested allergy or avoided ingredient is never treated as safe merely because a menu line omits it.

Scores use fixed evidence tiers: 90 for an explicitly labeled dietary match with a satisfied requested budget and no unresolved meal, cuisine, allergy, or avoid constraint; 60 for partial evidence; 35 when important facts remain unknown; and 0 for an excluded candidate. Exclusion requires explicit conflicting menu text or comparable printed prices that all exceed the budget. Results sort by status, score, name, then provider place ID.

Every extracted dish retains the source URL, exact line, and retrieval timestamp. Translation is presented separately and is not treated as source evidence. Printed price currency is not guessed from an ambiguous `$` sign. Budget checks require a matching explicit currency.

## Checks

From `backend/`: `uv run pytest` and `uv run ruff check app tests`.

From `frontend/`: `npm run lint`, `npm run typecheck`, and `npm run test`. The production build can be checked with `npm run build`.

## Deployment

Deploy `frontend/` from Vercel and deploy `backend/` as a Python ASGI service, for example with `uvicorn app.main:app`. Configure server-side provider keys and explicit CORS origins on the backend. Provider API usage may incur charges under the provider's account and terms.
