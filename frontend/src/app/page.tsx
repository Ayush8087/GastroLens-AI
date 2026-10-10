"use client";

import { useRef, useState, type FormEvent, type ReactNode } from "react";

type Restaurant = {
  restaurant_name: string | null;
  place_id: string | null;
  city_or_address: string | null;
  distance_meters?: number | null;
  official_website_url: string | null;
  menu_url: string | null;
  maps_url: string | null;
  business_status: string | null;
  location_match: "confirmed" | "unconfirmed";
  verification_status: "discovered" | "partially_verified" | "verified";
  match_status: "exact_match" | "partial_match" | "uncertain" | "excluded";
  score: number;
  match_reasons: string[];
  source_evidence: { url: string; title: string | null; snippet: string | null; accessible: boolean | null; retrieved_at: string }[];
  menu_items: { name: string; original_text: string; translated_text: string | null; description: string | null; translated_description: string | null; section: string | null; price: number | null; currency: string | null; source_url: string; evidence: string; evidence_type: "printed_text" | "ocr_transcription"; retrieved_at: string; dietary_status: "confirmed" | "contradicted" | "unknown"; allergen_status: "conflict" | "unknown"; warnings: string[] }[];
  unknown_fields: string[];
};

type SearchResponse = {
  criteria?: { allergies?: string[] };
  restaurants: Restaurant[];
  warnings: string[];
  provider_coverage: string;
};

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export default function Home() {
  const [query, setQuery] = useState("");
  const [location, setLocation] = useState("");
  const [coordinates, setCoordinates] = useState<{ latitude: number; longitude: number } | null>(null);
  const [locationMessage, setLocationMessage] = useState("");
  const [radius, setRadius] = useState("");
  const [meal, setMeal] = useState("");
  const [cuisine, setCuisine] = useState("");
  const [diet, setDiet] = useState("");
  const [budget, setBudget] = useState("");
  const [currency, setCurrency] = useState("");
  const [avoided, setAvoided] = useState("");
  const [allergies, setAllergies] = useState("");
  const [language, setLanguage] = useState("");
  const [preferences, setPreferences] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const activeRequest = useRef<AbortController | null>(null);

  async function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setProgress("Preparing your restaurant research");
    setError("");
    setResult(null);
    const controller = new AbortController();
    activeRequest.current = controller;
    try {
      const response = await fetch(`${API_BASE}/api/v1/restaurants/search/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          query: query.trim() || undefined,
          location: location.trim() || undefined,
          search_radius_meters: radius ? Number(radius) : coordinates ? 5000 : undefined,
          latitude: coordinates?.latitude,
          longitude: coordinates?.longitude,
          meal: meal || undefined,
          preferred_cuisine: cuisine.trim() || undefined,
          dietary_requirements: diet.split(",").map((item) => item.trim()).filter(Boolean),
          max_budget_per_person: budget ? Number(budget) : undefined,
          currency: currency.trim().toUpperCase() || undefined,
          avoided_ingredients: avoided.split(",").map((item) => item.trim()).filter(Boolean),
          allergies: allergies.split(",").map((item) => item.trim()).filter(Boolean),
          target_language: language.trim() || undefined,
          other_preferences: preferences.split(",").map((item) => item.trim()).filter(Boolean),
          max_results: 10,
        }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        const detail = body?.detail;
        throw new Error(typeof detail === "string" ? detail : `Search failed (${response.status}).`);
      }
      if (response.headers?.get("content-type")?.includes("text/event-stream") && response.body) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let finalResult: SearchResponse | null = null;
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let boundary = buffer.indexOf("\n\n");
          while (boundary >= 0) {
            const frame = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const event = frame.split("\n").find((line) => line.startsWith("event:"))?.slice(6).trim();
            const payload = frame.split("\n").find((line) => line.startsWith("data:"))?.slice(5).trim();
            if (event && payload) {
              const data = JSON.parse(payload) as { stage?: string; message?: string } & SearchResponse;
              if (event === "progress" && data.stage) setProgress(data.stage);
              if (event === "result") finalResult = data;
              if (event === "error") throw new Error(data.message || "Research could not be completed.");
            }
            boundary = buffer.indexOf("\n\n");
          }
        }
        if (!finalResult) throw new Error("The research stream ended before results arrived. Retry the search.");
        setResult(finalResult);
      } else {
        setResult((await response.json()) as SearchResponse);
      }
    } catch (caught) {
      if (!controller.signal.aborted) {
        setError(caught instanceof Error ? caught.message : "Search could not be completed.");
      }
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null;
      setLoading(false);
      setProgress("");
    }
  }

  function cancelSearch() {
    activeRequest.current?.abort();
    activeRequest.current = null;
    setLoading(false);
    setProgress("");
  }

  function useCurrentLocation() {
    if (!navigator.geolocation) {
      setLocationMessage("This browser does not support location access.");
      return;
    }
    setLocationMessage("Requesting location permission…");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLocation("");
        setCoordinates({ latitude: position.coords.latitude, longitude: position.coords.longitude });
        setLocationMessage("Using your current location. Google Places will search with a 5 km bias.");
      },
      () => setLocationMessage("Location permission was unavailable. Enter a city or address instead."),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 },
    );
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="GastroLens home"><span className="brand-mark">G</span>gastrolens</a>
        <span className="top-note"><span className="live-dot" /> Evidence-led restaurant research</span>
      </header>

      <section className="intro" id="top">
        <div className="eyebrow"><span className="eyebrow-line" /> YOUR NEXT TABLE, WELL RESEARCHED</div>
        <h1>Find a place worth<br /><em>sitting down for.</em></h1>
        <p className="intro-copy">Tell us what you’re in the mood for. We’ll look across real local listings and source pages, then show what we could verify.</p>
      </section>

      <section className="search-panel" aria-label="Restaurant search">
        <form onSubmit={submitSearch}>
          <label className="field-label" htmlFor="query">What are you looking for?</label>
          <div className="query-wrap"><span className="search-icon" aria-hidden="true">⌕</span><input id="query" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="A relaxed dinner near a local market…" /></div>
          <div className="form-grid">
            <div className="location-field"><label htmlFor="location">LOCATION</label><input id="location" value={location} onChange={(e) => { setLocation(e.target.value); if (e.target.value.trim()) setCoordinates(null); }} placeholder="City, region, or address" /><button className="text-button" type="button" onClick={useCurrentLocation}>Use my current location</button>{locationMessage && <small role="status">{locationMessage}</small>}</div>
            <label>SEARCH RADIUS (METRES) <input type="number" min="100" max="50000" step="100" value={radius} onChange={(e) => setRadius(e.target.value)} placeholder="Optional" /></label>
            <label>MEAL
              <select value={meal} onChange={(e) => setMeal(e.target.value)}><option value="">Any time</option><option value="breakfast">Breakfast</option><option value="lunch">Lunch</option><option value="dinner">Dinner</option></select>
            </label>
            <label>CUISINE <input value={cuisine} onChange={(e) => setCuisine(e.target.value)} placeholder="Optional" /></label>
            <label>DIETARY NEEDS <input value={diet} onChange={(e) => setDiet(e.target.value)} placeholder="e.g. vegetarian, vegan" /></label>
            <label>MAXIMUM PER PERSON <input type="number" min="0" step="0.01" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="Optional" /></label>
            <label>CURRENCY <input value={currency} onChange={(e) => setCurrency(e.target.value)} maxLength={3} placeholder="e.g. USD" /></label>
            <label>AVOID INGREDIENTS <input value={avoided} onChange={(e) => setAvoided(e.target.value)} placeholder="Comma-separated, optional" /></label>
            <label>ALLERGIES <input value={allergies} onChange={(e) => setAllergies(e.target.value)} placeholder="Comma-separated, optional" /></label>
            <label>TRANSLATE MENU TO <input value={language} onChange={(e) => setLanguage(e.target.value)} placeholder="e.g. English" /></label>
            <label>OTHER PREFERENCES <input value={preferences} onChange={(e) => setPreferences(e.target.value)} placeholder="e.g. outdoor seating, comma-separated" /></label>
          </div>
          <div className="form-footer"><span className="privacy-note"><span aria-hidden="true">◎</span> Your search goes to configured research providers</span><button className="submit-button" type="submit" disabled={loading || (!query.trim() && !location.trim() && !coordinates)}>{loading ? <><span className="button-spinner" /> Researching</> : <>Find restaurants <span aria-hidden="true">↗</span></>}</button></div>
        </form>
      </section>

      {loading && <section className="status-panel" role="status"><span className="loader-ring" /><div><strong>Researching your request</strong><p>{progress}</p></div><button type="button" className="text-button cancel-button" onClick={cancelSearch}>Cancel</button></section>}
      {error && <section className="notice error-notice" role="alert"><span>!</span><div><strong>We couldn’t complete that search.</strong><p>{error}</p><button className="text-button" onClick={(e) => { e.preventDefault(); document.querySelector<HTMLFormElement>("form")?.requestSubmit(); }}>Try again ↗</button></div></section>}

      {result && <section className="results" aria-live="polite">
        <div className="results-heading"><div><div className="eyebrow"><span className="eyebrow-line" /> RESEARCH RESULTS</div><h2>{result.restaurants.length ? `${result.restaurants.length} places to explore` : "No places found yet"}</h2></div><span className="results-count">{result.restaurants.length} {result.restaurants.length === 1 ? "result" : "results"}</span></div>
        {result.warnings.map((warning) => <div className="notice warning-notice" key={warning}><span>i</span><p>{warning}</p></div>)}
        {!result.restaurants.length && !result.warnings.length && <div className="empty-state"><span>⌕</span><strong>No restaurants came back for this search.</strong><p>Try another location or broaden your description.</p></div>}
        <div className="result-list">{result.restaurants.map((restaurant, index) => <RestaurantCard key={restaurant.place_id || restaurant.restaurant_name || index} restaurant={restaurant} index={index + 1} allergies={result.criteria?.allergies || []} />)}</div>
        {result.provider_coverage && <p className="coverage-note">{result.provider_coverage}</p>}
      </section>}

      {!result && !loading && !error && <div className="prompt-note"><span className="prompt-spark">✳</span><span>Search any destination. Results depend on the configured provider’s local coverage.</span></div>}
      <footer><span>gastrolens</span><span>Research with receipts.</span></footer>
    </main>
  );
}

function RestaurantCard({ restaurant, index, allergies }: { restaurant: Restaurant; index: number; allergies: string[] }) {
  const name = restaurant.restaurant_name || "Restaurant name unavailable";
  const status = restaurant.match_status === "exact_match" ? "Exact match" : restaurant.match_status === "partial_match" ? "Partial match" : restaurant.match_status === "excluded" ? "Excluded" : "Uncertain";
  return <article className="restaurant-card">
    <div className="card-index">{String(index).padStart(2, "0")}</div>
    <div className="card-main">
      <div className="card-topline"><span className="match-pill"><span />{status}</span><span className="verify-label">{restaurant.verification_status.replaceAll("_", " ")}</span></div>
      <h3>{name}</h3>
      <p className="restaurant-address">{restaurant.city_or_address || "Address not provided by listing provider"}{restaurant.distance_meters != null ? ` · ${(restaurant.distance_meters / 1000).toFixed(1)} km away` : ""}{restaurant.business_status ? ` · ${restaurant.business_status.toLowerCase().replaceAll("_", " ")}` : ""}{restaurant.location_match === "unconfirmed" ? " · location match unconfirmed" : ""}</p>
      {restaurant.menu_items.length > 0 ? <div className="dishes"><h4>MENU FINDINGS</h4>{restaurant.menu_items.map((dish) => <div className="dish" key={`${dish.source_url}-${dish.original_text}`}><div><div className="dish-title"><strong>{dish.translated_text || dish.name}</strong><span className={`dietary-pill dietary-${dish.dietary_status}`}>{dish.dietary_status === "confirmed" ? "Diet label confirmed" : dish.dietary_status === "contradicted" ? "Conflicts with request" : "Dietary status unknown"}</span></div>{dish.translated_text && <small>AI translation · original name: {dish.name}</small>}{dish.section && <small>Menu section: {dish.section}</small>}{dish.translated_description && <p>Translated description: {dish.translated_description}</p>}{dish.description && <p>Original description: {dish.description}</p>}{allergies.length ? <p className="dish-warning">{dish.allergen_status === "conflict" ? "Requested allergen appears in source text." : "Allergen safety is unconfirmed. Contact the restaurant before ordering."}</p> : null}<p className="evidence-quote">“{dish.evidence}”</p>{dish.evidence_type === "ocr_transcription" && <small>OCR transcription · unverified against searchable source text</small>}<SafeLink href={dish.source_url}>Dish source ↗</SafeLink>{dish.warnings.map((warning) => <p className="dish-warning" key={warning}>{warning}</p>)}<small>Source retrieved {new Date(dish.retrieved_at).toISOString().replace("T", " ").slice(0, 16)} UTC</small></div><span>{dish.price == null ? "Price not found" : `${dish.evidence_type === "ocr_transcription" ? "OCR · " : ""}${dish.currency ? `${dish.currency} ${dish.price.toFixed(2)}` : `${dish.price.toFixed(2)} · currency unclear`}${dish.evidence_type === "ocr_transcription" ? " · unverified" : ""}`}</span></div>)}</div> : <div className="uncertainty"><span>?</span><p>Menu and dietary suitability have not been verified. No dish or price is inferred from the listing.</p></div>}
      <div className="card-links">{restaurant.maps_url && <SafeLink href={restaurant.maps_url}>View listing ↗</SafeLink>}{restaurant.official_website_url && <SafeLink href={restaurant.official_website_url}>Website ↗</SafeLink>}{restaurant.menu_url && <SafeLink href={restaurant.menu_url}>Menu source ↗</SafeLink>}</div>
      {restaurant.source_evidence.length > 0 && <details className="sources"><summary>Sources &amp; evidence <span>({restaurant.source_evidence.length})</span></summary><ul>{restaurant.source_evidence.map((source, i) => <li key={`${source.url}-${i}`}><SafeLink href={source.url}>{source.title || source.url}</SafeLink>{source.snippet && <p>“{source.snippet}”</p>}<small>Retrieved {new Date(source.retrieved_at).toISOString().replace("T", " ").slice(0, 16)} UTC · {source.accessible === false ? "source inaccessible" : source.accessible === true ? "source accessible" : "not checked"}</small></li>)}</ul></details>}
    </div>
    <div className="score"><strong>{restaurant.score}<small>/100</small></strong><span>{restaurant.match_reasons.length ? restaurant.match_reasons.join(" · ") : "No dish-level score yet"}</span></div>
  </article>;
}

function SafeLink({ href, children }: { href: string; children: ReactNode }) {
  let safeHref: string;
  try {
    const url = new URL(href);
    if (!new Set(["http:", "https:"]).has(url.protocol)) return null;
    safeHref = url.toString();
  } catch { return null; }
  return <a href={safeHref} target="_blank" rel="noreferrer noopener">{children}</a>;
}
