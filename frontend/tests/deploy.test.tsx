import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Home from "../app/page";
import config from "../next.config";
import { api } from "../lib/api";

vi.mock("../components/journal", () => ({ Journal: () => <main>Journal</main> }));

describe("[p7] public deployment boundaries", () => {
  afterEach(() => { vi.unstubAllEnvs(); });
  it("rewrites API and health on the server and restricts browser connections", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://127.0.0.1:8000");
    expect(await config.rewrites?.()).toEqual([
      { source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" },
      { source: "/health", destination: "http://127.0.0.1:8000/health" },
    ]);
    expect(await config.headers?.()).toEqual([{ source: "/:path*", headers: [{ key: "Content-Security-Policy", value: "connect-src 'self'" }] }]);
  });
  it("rejects credential-bearing upstreams", async () => {
    vi.stubEnv("API_INTERNAL_URL", "https://user:secret@example.invalid");
    await expect(config.rewrites?.()).rejects.toThrow(/without credentials/);
  });
  it.each(["https://example.invalid/api/chat", "//example.invalid/api/chat", "/api/\\example.invalid"]) ("refuses cross-origin path %s before fetch", async path => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    await expect(api(path)).rejects.toMatchObject({ code: "origin" });
    expect(fetch).not.toHaveBeenCalled();
    vi.stubGlobal("fetch", () => { throw new Error("Network is disabled in tests"); });
  });
  it("keeps the demo privacy notice immediately below the disclaimer", () => {
    render(<Home />);
    const notice = screen.getByText("Demo: don’t enter real health information.");
    expect(notice).toBeVisible();
    expect(notice.previousElementSibling).toHaveTextContent("It is not medical advice.");
  });
});
