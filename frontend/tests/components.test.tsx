import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InsightCard } from "../components/insight-card";
import { ExperimentCard, PhaseLabel } from "../components/experiment-card";
import { ChatMessage } from "../components/chat-pane";
import { DemoControls } from "../components/demo-controls";
import type { ExperimentView, Insight, Phase } from "../lib/api";

const insight: Insight = { id: "i", exposure: "coffee", outcome: "fatigue", lag_days: 0, tier: "weak", effect: -1.5, n_pairs: 28, n_exposed: 12, n_unexposed: 16, confounder: "sleep", data_points: [{ outcome_date: "2026-02-01", exposure_date: "2026-02-01", x: 1, y: 4 }], eligible: true, ineligible_reason: null };
function experiment(phase: Phase): ExperimentView { return { today: "2026-02-15", experiment: { id: "e", exposure: "coffee", outcome: "fatigue", status: phase === "baseline" ? "baseline" : "running", started_on: "2026-02-15", protocol: { baseline_days: 2, n_blocks: 4, block_days: 3, washout_days: 1 }, verdict: null }, today_plan: { date: "2026-02-15", phase, washout: phase !== "baseline", adherence: null, outcome_value: null }, schedule: [], progress: { day: 1, total: 14 }, limitation: "This small, unblinded test concerns one person, uses day-level resampling, and assumes a short washout." }; }

describe("[p7] research journal components", () => {
  it("shows tier and sample size and expands frozen evidence", () => {
    const test = vi.fn(); render(<InsightCard insight={insight} busy={false} onTest={test} />);
    expect(screen.getByText("weak")).toBeVisible(); expect(screen.getByText(/28 paired days/)).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show data points" }));
    expect(screen.getByRole("table")).toBeVisible(); expect(screen.getByText(/Frozen evidence/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Test this" })); expect(test).toHaveBeenCalledWith(insight);
  });
  it.each(["baseline", "on", "off"] as const)("shows %s with a large text label and its own shape", phase => {
    render(<PhaseLabel phase={phase} />);
    expect(screen.getByText(phase.toUpperCase())).toHaveClass("text-3xl");
    const shape = screen.getByText(phase.toUpperCase()).previousElementSibling;
    if (phase === "on") expect(shape).toHaveClass("rounded-full");
    else if (phase === "off") expect(shape).toHaveClass("rotate-45");
    else expect(shape).toHaveClass("border-2");
  });
  it.each(["baseline", "on", "off"] as const)("renders the %s instruction correctly", phase => {
    render(<ExperimentCard data={experiment(phase)} busy={false} onAccept={vi.fn()} onAbandon={vi.fn()} onSave={vi.fn()} />);
    expect(screen.getByText(phase.toUpperCase())).toBeVisible();
    expect(screen.getByText(phase === "baseline" ? "Keep your usual routine." : "Follow your accepted plan.")).toBeVisible();
    if (phase === "baseline") expect(screen.queryByText(/Did you follow/)).not.toBeInTheDocument();
    else expect(screen.getByText(/This day is not counted/)).toBeVisible();
  });
  it("writes adherence and the bounded rating through the day callback", () => {
    const save = vi.fn(); render(<ExperimentCard data={experiment("on")} busy={false} onAccept={vi.fn()} onAbandon={vi.fn()} onSave={save} />);
    fireEvent.click(screen.getByRole("button", { name: "Yes" }));
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "6" } });
    fireEvent.click(screen.getByRole("button", { name: "Save today’s entry" }));
    expect(save).toHaveBeenCalledWith(true, 6);
  });
  it("shows the verdict, sample size and limitation at equal text size without celebration", () => {
    const data = experiment("on"); data.experiment!.verdict = { label: "helped", n_on: 4, n_off: 4, benefit: 2, ci_low: 1, ci_high: 3 };
    render(<ExperimentCard data={data} busy={false} onAccept={vi.fn()} onAbandon={vi.fn()} onSave={vi.fn()} />);
    expect(screen.getByText("Helped in this test")).toHaveClass("text-base");
    expect(screen.getByText(/Usable data: 4 ON days and 4 OFF days/)).toHaveClass("text-base");
    expect(screen.getByText(data.limitation)).toHaveClass("text-base");
  });
  it("renders red flags as high-contrast plain text alerts with a distinct border", () => {
    render(<ChatMessage message={{ id: "s", role: "assistant", red_flag: true, content: "Contact emergency services now. Call [988](tel:988)." }} />);
    expect(screen.getByRole("alert")).toHaveClass("border-4", "border-double", "bg-[#761a1a]");
    expect(screen.getByText("Contact emergency services now. Call 988.")).toBeVisible();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
  it("only renders simulated advance controls for demo users", () => {
    const props = { busy: false, remaining: 13, onLoad: vi.fn(), onAdvance: vi.fn() };
    const { rerender } = render(<DemoControls {...props} isDemo={false} />);
    expect(screen.queryByRole("button", { name: /Next day/ })).not.toBeInTheDocument();
    rerender(<DemoControls {...props} isDemo />);
    fireEvent.click(screen.getByRole("button", { name: /Next day.*simulated/ })); expect(props.onAdvance).toHaveBeenCalledWith(1);
    fireEvent.click(screen.getByRole("button", { name: /Skip to end.*simulated/ })); expect(props.onAdvance).toHaveBeenCalledWith(13);
  });
});
