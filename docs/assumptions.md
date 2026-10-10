# Assumptions

- Barcelona is the only initial destination; the foundation does not hard-code restaurant or neighbourhood data.
- "Vegetarian-friendly" will need an explicit product definition, since menus, cross-contamination statements, and restaurant claims vary.
- The initial meal slots are breakfast, lunch, and dinner. Budget, cuisine, language, dietary, accessibility, and trip-context filters will be designed as validated request fields when discovery is implemented.
- PostgreSQL will be used for durable data. Database access is not needed by the initial liveness endpoint.
- OpenAI and Tavily credentials remain backend-only. Discovery requires `TAVILY_API_KEY` to search; OpenAI is not used in this phase.
- Vercel is the frontend target; the backend target remains provider-neutral among Python-compatible ASGI hosts.

# Discovery assumptions

- Restaurant candidates are leads from Tavily search. A search result is not treated as a confirmed restaurant record.
- The requested city is search context and is not copied into a candidate's address field without source evidence.
- The budget is a search phrase only; the API cannot confirm prices until a later menu retrieval and extraction phase.
- `verified` means the linked source is accessible and its page text matches a name/domain candidate. It does not establish ownership, active operation, or dietary fit.
- The default vegetarian requirement guides search only. No result is described as vegetarian-friendly until menu evidence supports that claim.
