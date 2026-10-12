import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import Home from "./page";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("restaurant search experience", () => {
  it("turns an example search into editable criteria and submits those criteria", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ restaurants: [], warnings: [], provider_coverage: "" }),
    } as Response);
    render(<Home />);

    fireEvent.click(screen.getByRole("button", { name: /something green, somewhere quiet/i }));
    expect(screen.getByLabelText("What are you hungry for?")).toHaveValue(
      "Vegetarian food somewhere calm",
    );
    expect(screen.getByRole("radio", { name: "Dinner" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getAllByText("Vegetarian").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: /find restaurants/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toMatchObject({
      query: "Vegetarian food somewhere calm",
      meal: "dinner",
      dietary_requirements: ["Vegetarian"],
      other_preferences: ["Quiet atmosphere"],
    });
  });

  it("clears entered criteria from the filter controls", () => {
    render(<Home />);
    fireEvent.change(screen.getByLabelText("LOCATION"), { target: { value: "Kyoto" } });
    fireEvent.click(screen.getByRole("button", { name: /clear all/i }));

    expect(screen.getByLabelText("LOCATION")).toHaveValue("");
    expect(screen.queryByRole("button", { name: /clear all/i })).not.toBeInTheDocument();
  });

  it("supports keyboard meal selection and toggles dietary quick filters", () => {
    render(<Home />);
    const dinner = screen.getByRole("radio", { name: "Dinner" });
    fireEvent.keyDown(dinner, { key: "ArrowLeft" });
    expect(screen.getByRole("radio", { name: "Supper" })).toHaveAttribute("aria-checked", "true");

    const vegan = screen.getByRole("button", { name: /vegan/i });
    fireEvent.click(vegan);
    expect(vegan).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(vegan);
    expect(vegan).toHaveAttribute("aria-pressed", "false");
  });

  it("shows live research animation and backend progress while the request is pending", async () => {
    let finishRequest!: (response: Response) => void;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise((resolve) => { finishRequest = resolve; }));
    render(<Home />);
    fireEvent.change(screen.getByLabelText("LOCATION"), { target: { value: "Kyoto" } });
    fireEvent.click(screen.getByRole("button", { name: /find restaurants/i }));

    expect(await screen.findByText("We’re on the case")).toBeInTheDocument();
    expect(screen.getByText("LIVE RESEARCH")).toBeInTheDocument();
    expect(screen.getByText("Preparing your restaurant research")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cancel search/i })).toBeInTheDocument();
    finishRequest({ ok: true, headers: new Headers({ "content-type": "application/json" }), json: async () => ({ restaurants: [], warnings: [], provider_coverage: "" }) } as Response);
    expect(await screen.findByText("No places found yet")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("submits the user's location and displays real API results with uncertainty", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        restaurants: [{
          restaurant_name: "Garden Table",
          city_or_address: "Kyoto",
          official_website_url: null,
          menu_url: null,
          maps_url: "https://maps.example/place/1",
          business_status: "OPERATIONAL",
          rating: 4.6,
          review_count: 138,
          place_type: "Japanese restaurant",
          google_price_level: "PRICE_LEVEL_MODERATE",
          location_match: "confirmed",
          verification_status: "partially_verified",
          match_status: "uncertain",
          score: 35,
          match_reasons: ["Menu not found"],
          source_evidence: [],
          menu_items: [{
            name: "Mushroom noodles",
            original_text: "Mushroom noodles EUR 14.00",
            translated_text: null,
            description: null,
            price: 14,
            currency: "EUR",
            source_url: "https://restaurant.example/menu",
            evidence: "Mushroom noodles EUR 14.00",
            retrieved_at: "2026-10-10T12:00:00Z",
            dietary_status: "unknown",
            match_status: "needs_checking",
            match_reasons: ["Dietary suitability is not confirmed by this menu evidence."],
            warnings: ["Dietary status is not confirmed."],
          }],
          unknown_fields: ["menu"],
          place_id: "places/1",
        }],
        warnings: [],
        provider_coverage: "Coverage depends on provider.",
      }),
    } as Response);
    render(<Home />);
    fireEvent.change(screen.getByLabelText("LOCATION"), { target: { value: "Kyoto" } });
    const dietaryInput = screen.getByRole("combobox", { name: "Add another dietary need" });
    fireEvent.change(dietaryInput, { target: { value: "vegetarian" } });
    fireEvent.keyDown(dietaryInput, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: /find restaurants/i }));

    expect(await screen.findByRole("heading", { name: "Garden Table" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /needs checking/i })).toBeInTheDocument();
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/restaurants/search/stream");
    expect(screen.getByText(/Rated 4\.6 \(138 Google reviews\)/)).toBeInTheDocument();
    expect(screen.getByText("Japanese restaurant")).toBeInTheDocument();
    expect(screen.getByText("Google price level: Moderate (2 of 4)")).toBeInTheDocument();
    expect(screen.getByText("WHY IT MATCHES")).toBeInTheDocument();
    expect(screen.getByText("Dietary status unknown")).toBeInTheDocument();
    expect(screen.getByText("? Needs checking")).toBeInTheDocument();
    expect(screen.getByText("Dietary suitability is not confirmed by this menu evidence.")).toBeInTheDocument();
    expect(screen.getByText("EUR 14.00")).toBeInTheDocument();
    expect(screen.getByText(/Mushroom noodles EUR 14.00/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /view listing/i })).toHaveAttribute("href", "https://maps.example/place/1");
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toMatchObject({ location: "Kyoto", dietary_requirements: ["Vegetarian"] });
  });

  it("explains missing provider configuration without inventing results", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ restaurants: [], warnings: ["GOOGLE_PLACES_API_KEY is missing."], provider_coverage: "" }),
    } as Response);
    render(<Home />);
    fireEvent.change(screen.getByLabelText("LOCATION"), { target: { value: "Kyoto" } });
    fireEvent.click(screen.getByRole("button", { name: /find restaurants/i }));
    expect(await screen.findByText(/GOOGLE_PLACES_API_KEY is missing/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("0 results")).toBeInTheDocument());
  });

  it("shows request failures and retries when asked", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({ detail: "Provider is offline." }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ restaurants: [], warnings: [], provider_coverage: "" }) } as Response);
    render(<Home />);
    fireEvent.change(screen.getByLabelText("LOCATION"), { target: { value: "Osaka" } });
    fireEvent.click(screen.getByRole("button", { name: /find restaurants/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Provider is offline.");
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText(/try a broader location or adjust your filters/i)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("uses browser coordinates only after the user requests current location", async () => {
    const getCurrentPosition = vi.fn((success: PositionCallback) => success({
      coords: { latitude: 12.97, longitude: 77.59 },
    } as GeolocationPosition));
    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: { getCurrentPosition },
    });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ restaurants: [], warnings: [], provider_coverage: "" }),
    } as Response);
    render(<Home />);
    fireEvent.click(screen.getByRole("button", { name: /use my location/i }));
    expect(await screen.findByText(/using your current location/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /find restaurants/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toMatchObject({
      latitude: 12.97,
      longitude: 77.59,
      search_radius_meters: 5000,
    });
  });

  it("sends arbitrary locations, multi-select and custom filters to the real endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ restaurants: [], warnings: [], provider_coverage: "" }),
    } as Response);
    render(<Home />);
    fireEvent.change(screen.getByLabelText("LOCATION"), { target: { value: "Timbuktu Township" } });
    fireEvent.change(screen.getByLabelText("What are you hungry for?"), { target: { value: "Find a place for brunch" } });
    fireEvent.click(screen.getByRole("radio", { name: "Brunch" }));

    const cuisines = screen.getByRole("combobox", { name: "CUISINES" });
    fireEvent.change(cuisines, { target: { value: "Maharashtrian" } });
    fireEvent.keyDown(cuisines, { key: "Enter" });
    fireEvent.change(cuisines, { target: { value: "Assamese" } });
    fireEvent.keyDown(cuisines, { key: "Enter" });

    const diets = screen.getByRole("combobox", { name: "Add another dietary need" });
    fireEvent.change(diets, { target: { value: "Vegan" } });
    fireEvent.keyDown(diets, { key: "Enter" });
    fireEvent.change(diets, { target: { value: "High-protein" } });
    fireEvent.keyDown(diets, { key: "Enter" });

    fireEvent.change(screen.getByLabelText("MAXIMUM PER PERSON"), { target: { value: "450" } });
    fireEvent.change(screen.getByLabelText("Currency"), { target: { value: "INR" } });
    fireEvent.click(screen.getByText(/More preferences/));
    fireEvent.click(screen.getByText(/Allergies & ingredients/));
    const allergy = screen.getByRole("combobox", { name: "ALLERGIES" });
    fireEvent.change(allergy, { target: { value: "tree nuts" } });
    fireEvent.keyDown(allergy, { key: "Enter" });
    const avoided = screen.getByRole("combobox", { name: "INGREDIENTS TO AVOID" });
    fireEvent.change(avoided, { target: { value: "cilantro" } });
    fireEvent.keyDown(avoided, { key: "Enter" });
    const other = screen.getByRole("combobox", { name: "ATMOSPHERE & OTHER PREFERENCES" });
    fireEvent.change(other, { target: { value: "near a metro station" } });
    fireEvent.keyDown(other, { key: "Enter" });
    fireEvent.change(screen.getByLabelText("PARTY SIZE"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("TRANSLATE MENU TO"), { target: { value: "Marathi" } });

    fireEvent.click(screen.getByRole("button", { name: /find restaurants/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toMatchObject({
      query: "Find a place for brunch",
      location: "Timbuktu Township",
      meal: "brunch",
      preferred_cuisines: ["Maharashtrian", "Assamese"],
      dietary_requirements: ["Vegan", "High-protein"],
      max_budget_per_person: 450,
      currency: "INR",
      allergies: ["tree nuts"],
      avoided_ingredients: ["cilantro"],
      target_language: "Marathi",
      party_size: 5,
      other_preferences: ["near a metro station"],
    });
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/restaurants/search/stream");
  });

  it("removes a custom selection from its chip", () => {
    render(<Home />);
    const allergy = screen.getByRole("combobox", { name: "ALLERGIES" });
    fireEvent.change(allergy, { target: { value: "sesame" } });
    fireEvent.keyDown(allergy, { key: "Enter" });
    expect(screen.getByText("sesame")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove sesame" }));
    expect(screen.queryByText("sesame")).not.toBeInTheDocument();
  });
});
