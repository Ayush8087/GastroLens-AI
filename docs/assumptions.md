# Assumptions

- A requested location is supplied by the user directly or in natural-language text. No city, region, currency, cuisine, or dietary need is assumed.
- Google Places is the structured discovery integration; Tavily is a best-effort web fallback and source finder. Coverage and accuracy vary by provider and region; results are not complete local directories.
- Gemini may extract structured intent only when its values can be grounded in the user's text. Otherwise conservative phrase parsing is used; `near me` requires browser location permission or an entered place.
- A typed radius is a text search hint. Browser coordinates enable Google Places location bias and distance checks against returned place coordinates.
- A restaurant listing and its business status are provider assertions. Website checks do not prove legal ownership or that a business remains open.
- A menu line is matched only when a recognizable dish and printed price appear in source text. Gemini may transcribe a scanned PDF, but OCR findings remain unverified and cannot satisfy hard dietary or budget constraints.
- Dietary facts require explicit labels on a verified official menu page. Halal/kosher labels and allergy safety are not independently certified; avoid/allergy silence never establishes safety.
- Gemini translation is optional and preserves source fields. Translation is not evidence for ingredient or allergen claims.
- Provider keys stay in backend environment variables. PostgreSQL remains unused in this stateless slice.
