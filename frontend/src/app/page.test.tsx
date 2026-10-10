import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import Home from "./page";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("restaurant search experience", () => {
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
    fireEvent.change(screen.getByLabelText("DIETARY NEEDS"), { target: { value: "vegetarian" } });
    fireEvent.click(screen.getByRole("button", { name: /find restaurants/i }));

    expect(await screen.findByRole("heading", { name: "Garden Table" })).toBeInTheDocument();
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/restaurants/search/stream");
    expect(screen.getByText("Dietary status unknown")).toBeInTheDocument();
    expect(screen.getByText("EUR 14.00")).toBeInTheDocument();
    expect(screen.getByText(/Mushroom noodles EUR 14.00/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /view listing/i })).toHaveAttribute("href", "https://maps.example/place/1");
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toMatchObject({ location: "Kyoto", dietary_requirements: ["vegetarian"] });
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
    expect(await screen.findByText(/try another location or broaden your description/i)).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: /use my current location/i }));
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
});
