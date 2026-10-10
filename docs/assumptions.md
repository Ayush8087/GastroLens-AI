# Assumptions

- Barcelona is the only initial destination; the foundation does not hard-code restaurant or neighbourhood data.
- "Vegetarian-friendly" will need an explicit product definition, since menus, cross-contamination statements, and restaurant claims vary.
- The initial meal slots are breakfast, lunch, and dinner. Budget, cuisine, language, dietary, accessibility, and trip-context filters will be designed as validated request fields when discovery is implemented.
- PostgreSQL will be used for durable data. Database access is not needed by the initial liveness endpoint.
- OpenAI and Tavily are backend-only providers and are optional configuration until a real integration is built.
- Vercel is the frontend target; the backend target remains provider-neutral among Python-compatible ASGI hosts.
