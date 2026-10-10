# Assumptions

- A requested location is supplied by the user directly or in natural-language text. No city, region, currency, cuisine, or dietary need is assumed.
- Google Places is the current location-aware discovery integration. Its data coverage and accuracy vary by region; results are leads, not complete local directories.
- Exact phrase extraction from natural language is intentionally limited to clear meal, dietary, and `in/near/around <location>` patterns. The rest of the text is passed to the search provider as context.
- A restaurant listing and its business status are provider assertions. Website checks do not prove legal ownership or that a business remains open.
- A menu line is usable only when source text has a recognizable dish and printed price. PDF text extraction does not OCR scanned pages.
- Dietary facts require explicit menu text. Allergy/avoid terms present in a line contradict a match; their absence does not establish safety.
- OpenAI translation is optional and preserves the original text. Translation is not evidence for ingredient or allergen claims.
- Provider keys stay in backend environment variables. PostgreSQL remains unused in this stateless slice.
