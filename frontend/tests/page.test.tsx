import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Home from "../app/page";

describe("[p0] development landing page", () => {
  it("shows the project and persistent research disclaimer", () => {
    render(<Home />);
    expect(screen.getByRole("heading", { name: "Nof1" })).toBeInTheDocument();
    expect(screen.getByText(/It is not medical advice/)).toBeInTheDocument();
  });

  it("blocks outbound requests", () => {
    expect(() => fetch("https://example.com")).toThrow("Network is disabled");
  });
});
