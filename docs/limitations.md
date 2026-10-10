# Limitations

- **Provider coverage:** restaurant discovery requires Google Places and depends on Google coverage, listing quality, and API availability. This product does not promise worldwide completeness.
- **Search context:** natural-language parsing currently recognizes only explicit meal names, a small set of common dietary terms, and clear `in/near/around` locations. Other preferences remain search context; they are not converted into authoritative constraints.
- **Identity and freshness:** Google Places supplies listing identity/address/business status. Website name matching is a consistency check, not proof of ownership, and provider records can be stale.
- **Menus:** Tavily is used to find candidate menu URLs. Search snippets are not menu evidence. Only accessible HTML and text-based PDF content are extracted; scanned PDFs, image menus, complex tables, and no-price items may be missed.
- **Diet and allergens:** explicit labels and literal avoid terms are surfaced conservatively. The service cannot establish cross-contamination, ingredient absence, halal/kosher status, or allergy safety from silence. Unknown remains unknown.
- **Price and currency:** only printed prices are extracted. Currency is taken from an explicit code or unambiguous EUR/GBP symbol; `$` is intentionally ambiguous. Budget checks need matching currency and do not include tax, tip, or service fees unless printed as part of a dish price.
- **Translation:** requires `OPENAI_API_KEY`, may be unavailable, and is a translation aid. Original text and source evidence remain authoritative.
- **Availability:** a provider business status does not establish current opening hours, table availability, or reservation availability.
- **Security:** HTTP(S), private/local destinations, redirect targets, response size, and timeouts are checked. DNS validation is separate from connection resolution; production egress filtering or DNS-pinned transport would improve rebinding resistance.
- **No persistence:** PostgreSQL dependencies are present from the foundation but not used. Searches are synchronous and are not saved.
