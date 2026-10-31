import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";

describe("[p7] API client", () => {
  afterEach(() => { vi.stubGlobal("fetch", () => { throw new Error("Network is disabled in tests"); }); });
  it("preserves the backend error shape and sends credentials", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: false, status: 409, json: async () => ({ error: { code: "terminal", message: "This experiment has ended." } }) });
    vi.stubGlobal("fetch", fetch);
    await expect(api("/api/experiments/e/days/2026-02-15", { method: "PUT", body: { adherence: true } })).rejects.toMatchObject({ code: "terminal", status: 409, message: "This experiment has ended." });
    expect(fetch).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ credentials: "include", method: "PUT" }));
  });
  it("returns a safe connection error without exposing request text", async () => {
    vi.stubGlobal("fetch", () => { throw new Error("private-health-canary"); });
    await expect(api("/api/chat")).rejects.toMatchObject({ code: "connection", message: "Couldn’t reach Nof1. Please try again." });
  });
});
