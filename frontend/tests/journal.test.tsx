import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Home from "../app/page";
import { api, type ExperimentView, type Insight, type Tracking } from "../lib/api";

vi.mock("../lib/api", async importOriginal => ({ ...await importOriginal<typeof import("../lib/api")>(), api: vi.fn() }));
const mocked = vi.mocked(api);
const profile: Tracking = { outcomes: [{ name: "fatigue", direction_better: "lower" }], exposures: [{ name: "coffee" }], track_sleep: false, is_demo: false, today: "2026-02-14", clock_offset_days: -259 };
const pattern: Insight = { id: "i", exposure: "coffee", outcome: "fatigue", lag_days: 0, effect: -2, n_pairs: 30, n_exposed: 15, n_unexposed: 15, tier: "moderate", confounder: null, data_points: [], eligible: true, ineligible_reason: null };
const empty: ExperimentView = { experiment: null, today: "2026-02-14", today_plan: null, progress: { day: 0, total: 0 }, schedule: [], limitation: "This small, unblinded test concerns one person, uses day-level resampling, and assumes a short washout." };

describe("[p7] journal workflow using a fake API only", () => {
  beforeEach(() => { mocked.mockReset(); });
  it("establishes identity before fetching panes, then accepts and advances a demo", async () => {
    let demo = false;
    let current = empty;
    mocked.mockImplementation(async <T,>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> => {
      let data: unknown;
      if (path === "/api/tracking") data = { ...profile, is_demo: demo };
      else if (path === "/api/messages") data = [];
      else if (path === "/api/timeline?days=14") data = { today: current.today, days: [] };
      else if (path === "/api/insights") data = demo ? [pattern] : [];
      else if (path === "/api/experiments/current") data = current;
      else if (path === "/api/demo/load") { demo = true; data = { ...profile, is_demo: true }; }
      else if (path === "/api/experiments") { current = { ...empty, experiment: { id: "e", exposure: "coffee", outcome: "fatigue", status: "proposed", started_on: null, protocol: { baseline_days: 2, n_blocks: 4, block_days: 3, washout_days: 1 }, verdict: null } }; data = current; }
      else if (path === "/api/experiments/e/accept") { current = { ...current, experiment: { ...current.experiment!, status: "accepted", started_on: "2026-02-15" }, progress: { day: 0, total: 14 } }; data = current; }
      else if (path === "/api/demo/advance") { current = { ...current, today: "2026-02-15", experiment: { ...current.experiment!, status: "baseline" }, today_plan: { date: "2026-02-15", phase: "baseline", washout: false, adherence: null, outcome_value: null }, progress: { day: 1, total: 14 } }; data = { ...current, timeline: { today: current.today, days: [] }, insights: [pattern] }; }
      else if (path === "/api/experiments/e/days/2026-02-15" && options.method === "PUT") data = { id: "d" };
      else throw new Error(`Unexpected fake API path: ${path}`);
      return data as T;
    });
    render(<Home />);
    expect(mocked.mock.calls[0][0]).toBe("/api/tracking");
    await waitFor(() => expect(screen.getByRole("button", { name: "Load demo history" })).toBeEnabled());
    expect(mocked.mock.calls.map(call => call[0]).slice(1)).toEqual(expect.arrayContaining(["/api/messages", "/api/timeline?days=14", "/api/insights", "/api/experiments/current"]));
    fireEvent.click(screen.getByRole("button", { name: "Load demo history" }));
    fireEvent.click(await screen.findByRole("button", { name: "Test this" }));
    fireEvent.click(await screen.findByRole("button", { name: "Accept this plan" }));
    await screen.findByText(/Your accepted test starts/);
    const beforeAdvance = mocked.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: /Next day.*simulated/ }));
    expect(await screen.findByText("BASELINE")).toBeVisible();
    expect(mocked.mock.calls.slice(beforeAdvance).map(call => call[0])).toEqual(["/api/demo/advance"]);
    expect(screen.getByText(/It is not medical advice/)).toBeVisible();
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "6" } });
    fireEvent.click(screen.getByRole("button", { name: "Save today’s entry" }));
    await waitFor(() => expect(mocked).toHaveBeenCalledWith("/api/experiments/e/days/2026-02-15", expect.objectContaining({ method: "PUT", body: { adherence: true, outcome_value: 6 } })));
  });
  it("keeps the banner visible when initial loading fails", async () => {
    mocked.mockRejectedValue(new Error("offline"));
    render(<Home />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Couldn’t load your journal/);
    expect(screen.getByText(/It is not medical advice/)).toBeVisible();
  });
});
