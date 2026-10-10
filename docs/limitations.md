# Known limitations

- No restaurant discovery, identity verification, menu retrieval, PDF parsing flow, review analysis, ranking, or citation API is implemented.
- No database engine, session lifecycle, models, or Alembic migration environment is configured yet; only a declarative model base and dependencies exist.
- Provider protocols define replaceable boundaries but have no network implementation and do not imply that credentials or services are available.
- The health endpoint is process liveness only. It does not verify PostgreSQL, Tavily, or OpenAI.
- Source freshness, licensing and terms for collected content, multilingual quality, and dietary safety need explicit policies before production recommendations.
- Browser automation is intentionally omitted; Playwright should be added only for pages that cannot be handled through HTTPX and static extraction.

# Discovery limitations

- Tavily snippets are search-provider summaries. They can be stale or incomplete and are retained as leads, not proof of menu contents, prices, opening hours, or vegetarian suitability.
- Website classification uses conservative directory-host exclusions and a name/domain token match. It does not establish legal ownership; `verified` only describes an accessible page whose text matches the discovered name.
- The engine deduplicates normalized URLs and does not merge separate pages into restaurant identities. Search can return multiple pages or branches for the same restaurant.
- Menu URLs may be discovered, but this phase does not parse HTML or PDF menus. An accessibility result does not establish that a page is a menu or that its contents are current.
- The verifier checks DNS addresses before requests and manually validates redirects. DNS can change between validation and connection; a future deployment should consider outbound network egress controls or DNS-pinned transport for stronger rebinding protection.
- Search and verification are synchronous with the request and bounded to three provider searches and at most twenty returned candidates. Large-scale crawling, caching, persistence, and background processing are not included.
- No database, OpenAI call, review analysis, translation, ranking, or restaurant availability check is performed.
