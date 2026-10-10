# Known limitations

- No restaurant discovery, identity verification, menu retrieval, PDF parsing flow, review analysis, ranking, or citation API is implemented.
- No database engine, session lifecycle, models, or Alembic migration environment is configured yet; only a declarative model base and dependencies exist.
- Provider protocols define replaceable boundaries but have no network implementation and do not imply that credentials or services are available.
- The health endpoint is process liveness only. It does not verify PostgreSQL, Tavily, or OpenAI.
- Source freshness, licensing and terms for collected content, multilingual quality, and dietary safety need explicit policies before production recommendations.
- Browser automation is intentionally omitted; Playwright should be added only for pages that cannot be handled through HTTPX and static extraction.
