"use client";

import { useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";

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
  criteria?: { allergies?: string[]; dietary_requirements?: string[]; preferred_cuisines?: string[]; party_size?: number | null };
  restaurants: Restaurant[];
  warnings: string[];
  provider_coverage: string;
};

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const promptExamples = [
  { label: "Something green, somewhere quiet", query: "Vegetarian food somewhere calm", meal: "dinner", dietary: ["Vegetarian"], cuisines: [], preferences: ["Quiet atmosphere"] },
  { label: "Spicy Indian food tonight", query: "Spicy Indian food for dinner", meal: "dinner", dietary: [], cuisines: ["Indian"], preferences: [] },
  { label: "A cozy dinner for two", query: "A cozy dinner for two", meal: "dinner", dietary: [], cuisines: [], preferences: ["Romantic atmosphere"], partySize: "2" },
  { label: "A bright, unhurried brunch", query: "A relaxed brunch with fresh, seasonal food", meal: "brunch", dietary: [], cuisines: [], preferences: ["Quiet atmosphere"] },
  { label: "Gluten-free food, my kind of budget", query: "Gluten-free dishes within my budget", meal: "", dietary: ["Gluten-free"], cuisines: [], preferences: [] },
  { label: "Something local and new", query: "Find a local specialty I have not tried before", meal: "", dietary: [], cuisines: [], preferences: [] },
];
const dietOptions = ["Vegetarian", "Vegan", "Non-vegetarian", "Pescatarian", "Eggetarian", "Gluten-free", "Dairy-free", "Egg-free", "Halal", "Kosher", "Jain", "Lactose-free", "Keto", "Low-carb", "High-protein"];
const mealOptions = [
  { label: "Any meal", value: "", glyph: "✳" },
  { label: "Breakfast", value: "breakfast", glyph: "☀" },
  { label: "Brunch", value: "brunch", glyph: "◒" },
  { label: "Lunch", value: "lunch", glyph: "◉" },
  { label: "Supper", value: "supper", glyph: "◷" },
  { label: "Dinner", value: "dinner", glyph: "☾" },
];
const quickDietOptions = [
  { label: "Vegetarian", glyph: "◉" }, { label: "Vegan", glyph: "✳" },
  { label: "Non-vegetarian", glyph: "◧" }, { label: "Pescatarian", glyph: "≈" },
  { label: "Gluten-free", glyph: "GF" }, { label: "Dairy-free", glyph: "DF" },
  { label: "Egg-free", glyph: "EF" }, { label: "Halal", glyph: "H" },
  { label: "Kosher", glyph: "K" }, { label: "Jain", glyph: "J" },
];
const cuisineOptions = ["Italian", "Indian", "Chinese", "Japanese", "Korean", "Thai", "Mexican", "Mediterranean", "Middle Eastern", "American", "French", "Spanish", "Vietnamese", "Lebanese", "Continental", "Street food"];
const preferenceOptions = ["Quiet atmosphere", "Outdoor seating", "Good for groups", "Wheelchair accessibility", "Good value", "Near public transport", "Laptop-friendly", "Romantic atmosphere"];
const currencies = ["INR", "USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "CNY", "SGD", "AED", "NZD", "ZAR"];

export default function Home() {
  const [query, setQuery] = useState("");
  const [location, setLocation] = useState("");
  const [coordinates, setCoordinates] = useState<{ latitude: number; longitude: number } | null>(null);
  const [locationMessage, setLocationMessage] = useState("");
  const [radius, setRadius] = useState("");
  const [meal, setMeal] = useState("");
  const [cuisines, setCuisines] = useState<string[]>([]);
  const [dietary, setDietary] = useState<string[]>([]);
  const [budget, setBudget] = useState("");
  const [currency, setCurrency] = useState("");
  const [allergies, setAllergies] = useState<string[]>([]);
  const [avoided, setAvoided] = useState<string[]>([]);
  const [preferences, setPreferences] = useState<string[]>([]);
  const [language, setLanguage] = useState("");
  const [partySize, setPartySize] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const activeRequest = useRef<AbortController | null>(null);

  const advancedCount = allergies.length + avoided.length + preferences.length + (language ? 1 : 0) + (partySize ? 1 : 0) + (radius ? 1 : 0);
  const hasSearchCriteria = Boolean(query.trim() || location.trim() || coordinates || meal || cuisines.length || dietary.length || budget || currency || advancedCount);
  const activeSummary = [
    query.trim() ? `Request: ${query.trim()}` : "",
    location.trim() || (coordinates ? "Current location" : ""),
    meal,
    ...cuisines,
    ...dietary,
    ...allergies.map((value) => `Allergy: ${value}`),
    ...avoided.map((value) => `Avoid: ${value}`),
    ...(budget ? [`Up to ${currency ? `${currency} ` : ""}${budget} per person`] : []),
    ...preferences,
    ...(partySize ? [`${partySize} diners`] : []),
    ...(language ? [`Translate to ${language}`] : []),
  ].filter(Boolean);

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
          preferred_cuisines: cuisines,
          dietary_requirements: dietary,
          max_budget_per_person: budget ? Number(budget) : undefined,
          currency: currency.trim().toUpperCase() || undefined,
          avoided_ingredients: avoided,
          allergies,
          target_language: language.trim() || undefined,
          party_size: partySize ? Number(partySize) : undefined,
          other_preferences: preferences,
          max_results: 10,
        }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(typeof body?.detail === "string" ? body.detail : `Search failed (${response.status}).`);
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
      if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Search could not be completed.");
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
      () => setLocationMessage("Location permission was unavailable. Enter any city or address instead."),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 },
    );
  }

  function setExample(example: (typeof promptExamples)[number]) {
    setQuery(example.query);
    setMeal(example.meal);
    setDietary(example.dietary);
    setCuisines(example.cuisines);
    setPreferences(example.preferences);
    setPartySize(example.partySize || "");
    document.getElementById("query")?.focus();
  }

  function handleMealKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let nextIndex = index;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") nextIndex = (index + 1) % mealOptions.length;
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") nextIndex = (index - 1 + mealOptions.length) % mealOptions.length;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = mealOptions.length - 1;
    else return;
    event.preventDefault();
    setMeal(mealOptions[nextIndex].value);
    document.getElementById(`meal-${nextIndex}`)?.focus();
  }

  function clearAll() {
    setQuery(""); setLocation(""); setCoordinates(null); setLocationMessage("");
    setRadius(""); setMeal(""); setCuisines([]); setDietary([]); setBudget("");
    setCurrency(""); setAllergies([]); setAvoided([]); setPreferences([]);
    setLanguage(""); setPartySize(""); setResult(null); setError("");
  }

  function editSearch() {
    const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    document.getElementById("search")?.scrollIntoView({ behavior, block: "start" });
    document.getElementById("query")?.focus({ preventScroll: true });
  }

  return (
    <main className="app-shell">
      <header className="topbar" id="top">
        <a className="brand" href="#top" aria-label="GastroLens home"><span className="brand-mark">g</span><span>GastroLens<span className="brand-ai"> / field notes</span></span></a>
        <nav className="site-nav" aria-label="Main navigation"><a href="#how-it-works">The method</a><a href="#search">Search</a><a className="nav-cta" href="#search">Find a table <span aria-hidden="true">↗</span></a></nav>
      </header>

      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-meta"><span>INDEPENDENT FOOD RESEARCH</span><span>ISSUE 01 <i>·</i> MADE FOR YOUR APPETITE</span></div>
        <div className="hero-copy">
          <h1 id="hero-title">Eat well.<br /><span className="headline-mark">Know why.</span></h1>
          <p className="intro-copy">GastroLens finds real restaurants, reads actual menus, and checks individual dishes against what matters to you.</p>
          <div className="hero-links"><a className="hero-cta" href="#search"><span aria-hidden="true">⌕</span> Find my table <b aria-hidden="true">↘</b></a><span className="hero-note">No made-up menus.<br />No mystery ingredients.</span></div>
          <div className="food-illustrations" aria-hidden="true"><FoodArt /></div>
        </div>
      </section>

      <section className="approach-strip" id="how-it-works" aria-label="How GastroLens researches restaurants">
        <span className="method-label">OUR RECIPE</span>
        <div><span className="approach-number">01</span><span><strong>Find real restaurants</strong><small>Listings from configured providers</small></span></div>
        <div><span className="approach-number">02</span><span><strong>Read the actual menu</strong><small>Sources stay attached</small></span></div>
        <div><span className="approach-number">03</span><span><strong>Check every dish</strong><small>Unknowns stay unknown</small></span></div>
        <div><span className="approach-number">04</span><span><strong>Rank with reasons</strong><small>Evidence before enthusiasm</small></span></div>
      </section>

      <section className="search-panel" aria-label="Restaurant search" id="search">
        <form onSubmit={submitSearch}>
          <div className="search-panel-head"><div><span className="step-kicker">YOUR TABLE, YOUR TERMS</span><label className="field-label" htmlFor="query">What are you hungry for?</label></div><span className="order-note">RESEARCH NOTE <b>№ 01</b></span></div>
          <textarea id="query" maxLength={500} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Describe the meal, place, or atmosphere you have in mind…" rows={3} />
          <div className="prompt-examples" aria-label="Example searches"><span>NEED A STARTING POINT? PICK A NOTE</span>{promptExamples.map((example, index) => <button type="button" key={example.label} onClick={() => setExample(example)}><i aria-hidden="true">0{index + 1}</i>{example.label}<span aria-hidden="true"> ↗</span></button>)}</div>

          <div className="filters-heading"><div><span className="step-kicker">MAKE IT YOURS</span><h2>Choose your filters</h2></div><div className="filter-tools"><span className="optional-label">Every field is optional</span>{hasSearchCriteria && <button type="button" className="clear-button" onClick={clearAll}>Clear all</button>}</div></div>
          <div className="filter-grid">
            <div className="filter-field location-field"><label htmlFor="location">LOCATION <span>Any city, area, region, or country</span></label><div className="location-control"><span aria-hidden="true">⌖</span><input id="location" aria-label="LOCATION" maxLength={160} autoComplete="off" value={location} onChange={(event) => { setLocation(event.target.value); setCoordinates(null); setLocationMessage(""); }} placeholder="Where are you eating?" />{(location || coordinates) && <button type="button" aria-label="Clear location" onClick={() => { setLocation(""); setCoordinates(null); setLocationMessage(""); }}>×</button>}</div><button className="inline-action" type="button" onClick={useCurrentLocation}>◎ Use my location</button>{locationMessage && <small role="status">{locationMessage}</small>}</div>
            <div className="filter-field meal-field"><div><label>MEAL</label><span className="field-hint">Pick a time of day</span></div><div className="meal-tiles" role="radiogroup" aria-label="Meal">{mealOptions.map((option, index) => <button id={`meal-${index}`} type="button" role="radio" aria-label={option.label} aria-checked={meal === option.value} tabIndex={meal === option.value ? 0 : -1} className={meal === option.value ? "meal-tile is-selected" : "meal-tile"} key={option.label} onClick={() => setMeal(option.value)} onKeyDown={(event) => handleMealKeyDown(event, index)}><span className="meal-glyph" aria-hidden="true">{option.glyph}</span><span>{option.label}</span></button>)}</div></div>
            <div className="filter-field"><TagPicker label="CUISINES" hint="Choose any number or add your own" values={cuisines} options={cuisineOptions} placeholder="Search or add a cuisine" maxValues={8} maxEntryLength={80} onChange={setCuisines} /></div>
            <div className="filter-field diet-field"><div><label>DIETARY NEEDS</label><span className="field-hint">Choose all that apply. Suitability is checked dish by dish.</span></div><div className="quick-diets">{quickDietOptions.map((option) => <button type="button" key={option.label} aria-pressed={dietary.includes(option.label)} disabled={!dietary.includes(option.label) && dietary.length >= 8} className={dietary.includes(option.label) ? "diet-chip is-selected" : "diet-chip"} onClick={() => setDietary(dietary.includes(option.label) ? dietary.filter((value) => value !== option.label) : [...dietary, option.label])}><span aria-hidden="true">{option.glyph}</span>{option.label}{dietary.includes(option.label) && <b aria-hidden="true">✓</b>}</button>)}</div><TagPicker label="Add another dietary need" hint="Search or enter a custom requirement" values={dietary.filter((item) => !quickDietOptions.some((option) => option.label === item))} options={dietOptions.filter((item) => !dietary.includes(item))} placeholder="Search or add another" maxValues={Math.max(0, 8 - dietary.filter((item) => quickDietOptions.some((option) => option.label === item)).length)} maxEntryLength={50} onChange={(customValues) => setDietary([...dietary.filter((item) => quickDietOptions.some((option) => option.label === item)), ...customValues])} /></div>
            <div className="filter-field"><label htmlFor="budget">MAXIMUM PER PERSON <span>Menu price ceiling</span></label><div className="budget-row"><input id="budget" aria-label="MAXIMUM PER PERSON" type="number" min="0.01" max="100000" step="0.01" value={budget} onChange={(event) => setBudget(event.target.value)} placeholder="Any budget" /><input aria-label="Currency" list="currency-options" maxLength={3} value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} placeholder="Currency" /><datalist id="currency-options">{currencies.map((code) => <option key={code} value={code} />)}</datalist></div></div>
            <details className="advanced-filters">
              <summary><span className="summary-plus">＋</span><span><strong>More preferences</strong><small>Allergies, ingredients, dining style, party and language</small></span>{advancedCount > 0 && <span className="active-count">{advancedCount} active</span>}</summary>
              <details className="advanced-group"><summary>Allergies &amp; ingredients <span>Tell us what must be avoided</span></summary><div className="advanced-grid"><div className="filter-field"><TagPicker label="ALLERGIES" hint="Unknown status is never considered safe" values={allergies} options={[]} placeholder="Type an allergen and press Enter" maxValues={20} maxEntryLength={70} onChange={setAllergies} /></div><div className="filter-field"><TagPicker label="INGREDIENTS TO AVOID" hint="Enter any ingredient or preparation" values={avoided} options={[]} placeholder="Type an ingredient and press Enter" maxValues={30} maxEntryLength={70} onChange={setAvoided} /></div></div><p className="safety-note"><span>!</span> Menu data can be incomplete. This research cannot guarantee allergen safety. Confirm allergies directly with the restaurant before ordering.</p></details>
              <details className="advanced-group"><summary>Dining preferences <span>Atmosphere and accessibility hints</span></summary><div className="advanced-grid"><div className="filter-field advanced-span"><TagPicker label="ATMOSPHERE & OTHER PREFERENCES" hint="These may be sent as search hints, not verified facts" values={preferences} options={preferenceOptions} placeholder="Search or add a preference" maxValues={12} maxEntryLength={70} onChange={setPreferences} /></div></div></details>
              <details className="advanced-group"><summary>Your table <span>Party size and search radius</span></summary><div className="advanced-grid"><label className="filter-field">SEARCH RADIUS <span>Exact radius needs current location</span><input aria-label="SEARCH RADIUS" type="number" min="100" max="50000" step="100" value={radius} onChange={(event) => setRadius(event.target.value)} placeholder={coordinates ? "5,000 m default" : "Optional · metres"} /></label><label className="filter-field">PARTY SIZE <span>Number of diners</span><input aria-label="PARTY SIZE" type="number" min="1" max="50" value={partySize} onChange={(event) => setPartySize(event.target.value)} placeholder="Optional" /></label></div></details>
              <details className="advanced-group"><summary>Language <span>Keep original menu text alongside translation</span></summary><div className="advanced-grid"><label className="filter-field">TRANSLATE MENU TO <span>Original text stays visible</span><input aria-label="TRANSLATE MENU TO" value={language} onChange={(event) => setLanguage(event.target.value)} placeholder="Any language" /></label></div></details>
            </details>
          </div>

          {activeSummary.length > 0 && <div className="active-summary"><span className="active-label">YOUR SEARCH INCLUDES</span><div>{activeSummary.map((value, index) => <span key={`${value}-${index}`} className="summary-chip">{value}</span>)}</div></div>}
          <p className="filter-precedence">Selected filters take precedence over conflicting details in your description.</p>
          <div className="form-footer"><span className="privacy-note"><span aria-hidden="true">◈</span> Your selections are sent to configured research providers</span><button className="submit-button" type="submit" disabled={loading || (!query.trim() && !location.trim() && !coordinates)}>{loading ? <><span className="button-spinner" /> Researching</> : <>Find restaurants <span aria-hidden="true">↗</span></>}</button></div>
        </form>
      </section>

      {loading && <><section className="status-panel" role="status" aria-live="polite"><div className="research-orbit" aria-hidden="true"><span /><i /><b /></div><div className="research-progress"><div className="research-title"><div><strong>We’re on the case</strong><p>{progress || "Preparing your restaurant research"}</p></div><span className="live-tag"><i /> LIVE RESEARCH</span></div><div className="research-steps">{["Find places", "Check sources", "Read menus", "Match dishes"].map((step, index) => <span key={step} className={index <= researchStep(progress) ? "research-step is-active" : "research-step"}><i>{index < researchStep(progress) ? "✓" : `0${index + 1}`}</i>{step}</span>)}</div></div><button type="button" className="inline-action cancel-action" onClick={cancelSearch}>Cancel search</button></section><div className="skeleton-list" aria-hidden="true"><div className="skeleton-card"><i /><span /><span /><b /></div><div className="skeleton-card"><i /><span /><span /><b /></div></div></>}
      {error && <section className="notice error-notice" role="alert"><span>!</span><div><strong>We couldn’t complete that search.</strong><p>{error}</p><button className="inline-action" onClick={(event) => { event.preventDefault(); document.querySelector<HTMLFormElement>("form")?.requestSubmit(); }}>Try again ↗</button></div></section>}

      {result && <section className="results" aria-live="polite" id="results">
        <div className="results-heading"><div><div className="eyebrow"><span className="eyebrow-line" /> YOUR RESEARCH</div><h2>{result.restaurants.length ? `${result.restaurants.length} places to explore` : "No places found yet"}</h2></div><div className="results-actions"><span className="results-count">{result.restaurants.length} {result.restaurants.length === 1 ? "result" : "results"}</span><button type="button" className="edit-search" onClick={editSearch}>Edit search ↗</button></div></div>
        {result.warnings.map((warning) => <div className="notice warning-notice" key={warning}><span>i</span><p>{warning}</p></div>)}
        {!result.restaurants.length && <div className="empty-state"><span>⌕</span><strong>No places to show for this search.</strong><p>Try a broader location or adjust your filters. If a provider is not configured, its warning appears above.</p></div>}
        <div className="result-list">{result.restaurants.map((restaurant, index) => <RestaurantCard key={restaurant.place_id || restaurant.restaurant_name || index} restaurant={restaurant} index={index + 1} allergies={result.criteria?.allergies || []} />)}</div>
        {result.provider_coverage && <p className="coverage-note">{result.provider_coverage}</p>}
      </section>}

      {!result && !loading && !error && <div className="prompt-note"><span>✳</span><span>Real listings. Menu evidence. Clear uncertainty.</span></div>}
      <footer><span>gastrolens.ai</span><span>Research with receipts.</span></footer>
    </main>
  );
}

function researchStep(progress: string) {
  const stage = progress.toLocaleLowerCase();
  if (stage.includes("matching") || stage.includes("ranking")) return 3;
  if (stage.includes("reading")) return 2;
  if (stage.includes("checking") || stage.includes("found")) return 1;
  return 0;
}

function FoodArt() {
  return <>
    <svg className="art-plate" viewBox="0 0 340 340"><circle cx="170" cy="170" r="155" fill="#f9fbff"/><circle cx="170" cy="170" r="118" fill="#dbeafa"/><circle cx="170" cy="170" r="91" fill="#fff"/><path d="M117 183c10-41 50-64 89-45 32 16 42 50 17 73-18 17-40 11-49-4-10-17-1-36 17-40m-60 66c22 9 39 3 50-11m-39-97c6 13 17 18 29 17" fill="none" stroke="#f58237" strokeWidth="12" strokeLinecap="round"/><path d="M136 128l-8-14m27 3-2-17m22 21 7-14m-48 104-13 9m65 10 7 14" stroke="#a9cd37" strokeWidth="9" strokeLinecap="round"/><path d="M251 53l14-24m-1 45 29-4m-47-24-20-17" stroke="#fff" strokeWidth="5" strokeLinecap="round"/></svg>
    <svg className="art-spark" viewBox="0 0 100 100"><path d="M50 3l9 33 32-15-23 28 29 17-35-3-4 34-12-32-30 16 21-29L7 35l34 8z" fill="#c5e84b"/></svg>
    <span className="art-caption">GOOD THINGS<br />ON THE MENU</span>
  </>;
}

function TagPicker({ label, hint, values, options, placeholder, maxValues, maxEntryLength, onChange }: { label: string; hint: string; values: string[]; options: string[]; placeholder: string; maxValues: number; maxEntryLength: number; onChange: (values: string[]) => void }) {
  const [input, setInput] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listId = `options-${label.toLocaleLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  const filtered = options.filter((option) => option.toLocaleLowerCase().includes(input.trim().toLocaleLowerCase()) && !values.some((value) => value.toLocaleLowerCase() === option.toLocaleLowerCase())).slice(0, 8);
  const exactSelected = values.some((value) => value.toLocaleLowerCase() === input.trim().toLocaleLowerCase());

  function add(value: string) {
    const cleaned = value.trim().replace(/\s+/g, " ");
    if (cleaned && values.length < maxValues && !values.some((item) => item.toLocaleLowerCase() === cleaned.toLocaleLowerCase())) onChange([...values, cleaned]);
    setInput("");
    setOpen(false);
    setActive(0);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" && filtered.length) {
      event.preventDefault(); setOpen(true); setActive((active + 1) % filtered.length);
    } else if (event.key === "ArrowUp" && filtered.length) {
      event.preventDefault(); setActive((active - 1 + filtered.length) % filtered.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (open && filtered.length && active >= 0) add(filtered[active]);
      else add(input);
    } else if (event.key === "Escape") {
      setOpen(false);
    } else if (event.key === "Backspace" && !input && values.length) {
      onChange(values.slice(0, -1));
    }
  }

  return <div className="tag-picker">
    <label htmlFor={`${listId}-input`}>{label} <span>{hint}</span></label>
    <div className="tag-control" onClick={() => document.getElementById(`${listId}-input`)?.focus()}>
      <div className="chips">{values.map((value) => <span className="chip" key={value}><span>{value}</span><button type="button" aria-label={`Remove ${value}`} onClick={(event) => { event.stopPropagation(); onChange(values.filter((item) => item !== value)); }}>×</button></span>)}
        <input id={`${listId}-input`} role="combobox" aria-label={label} aria-autocomplete="list" aria-expanded={open && filtered.length > 0} aria-controls={listId} maxLength={maxEntryLength} value={input} placeholder={values.length ? "Add another…" : placeholder} disabled={values.length >= maxValues} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onChange={(event) => { setInput(event.target.value); setOpen(true); setActive(0); }} onKeyDown={onKeyDown} />
      </div>
      {open && filtered.length > 0 && <div className="option-list" role="listbox" id={listId}>{filtered.map((option, index) => <button type="button" role="option" aria-selected={index === active} key={option} className={index === active ? "option-active" : ""} onMouseDown={(event) => event.preventDefault()} onClick={() => add(option)}>{option}<span>{values.some((value) => value.toLocaleLowerCase() === option.toLocaleLowerCase()) ? "Selected" : "＋"}</span></button>)}</div>}
    </div>
    {values.length >= maxValues && <small role="status" className="limit-note">Maximum {maxValues} selections</small>}
    {input.trim() && !exactSelected && <button type="button" className="add-custom" onClick={() => add(input)}>＋ Add “{input.trim()}”</button>}
  </div>;
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
      {restaurant.source_evidence.length > 0 && <details className="sources"><summary>Sources &amp; evidence <span>({restaurant.source_evidence.length})</span></summary><ul>{restaurant.source_evidence.map((source, sourceIndex) => <li key={`${source.url}-${sourceIndex}`}><SafeLink href={source.url}>{source.title || source.url}</SafeLink>{source.snippet && <p>“{source.snippet}”</p>}<small>Retrieved {new Date(source.retrieved_at).toISOString().replace("T", " ").slice(0, 16)} UTC · {source.accessible === false ? "source inaccessible" : source.accessible === true ? "source accessible" : "not checked"}</small></li>)}</ul></details>}
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
