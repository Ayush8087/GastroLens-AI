import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "./page";

describe("home page", () => {
  it("describes the foundation without presenting fabricated restaurant data", () => {
    const page = render(<Home />);
    expect(page.getByRole("heading", { name: /restaurant research, grounded in evidence/i })).toBeInTheDocument();
    expect(page.getByText(/have not been enabled yet/i)).toBeInTheDocument();
  });
});
