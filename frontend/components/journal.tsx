"use client";
import { useEffect, useRef, useState } from "react";
import { api, ApiError, button, type AdvanceReply, type ChatReply, type ExperimentView, type Insight, type Message, type Timeline, type Tracking } from "../lib/api";
import { ChatPane } from "./chat-pane";
import { DemoControls } from "./demo-controls";
import { ExperimentCard } from "./experiment-card";
import { InsightCard } from "./insight-card";
import { TimelinePane } from "./timeline-pane";

export function Journal() {
  const [tracking, setTracking] = useState<Tracking | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [insights, setInsights] = useState<Insight[]>([]);
  const [experiment, setExperiment] = useState<ExperimentView | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const retry = useRef<{ text: string; id: string } | null>(null);

  useEffect(() => {
    let live = true;
    (async () => {
      // Establish the identity cookie before parallel requests, so a first visit
      // cannot accidentally create a different user for each pane.
      const profile = await api<Tracking>("/api/tracking");
      const [history, days, patterns, current] = await Promise.all([api<Message[]>("/api/messages"), api<Timeline>("/api/timeline?days=14"), api<Insight[]>("/api/insights"), api<ExperimentView>("/api/experiments/current")]);
      if (live) { setTracking(profile); setMessages(history); setTimeline(days); setInsights(patterns); setExperiment(current); setLoaded(true); }
    })().catch(() => { if (live) setError("Couldn’t load your journal. Check the connection and reload this page."); });
    return () => { live = false; };
  }, []);

  async function action(work: () => Promise<void>): Promise<void> {
    setBusy(true); setError(null);
    try { await work(); } catch (error) { setError(error instanceof ApiError ? error.message : "That request could not be completed. Please try again."); throw error; } finally { setBusy(false); }
  }
  function run(work: () => Promise<void>) { void action(work).catch(() => undefined); }
  async function loadDemo() {
    const profile = await api<Tracking>("/api/demo/load", { method: "POST" });
    const [days, patterns, current] = await Promise.all([api<Timeline>("/api/timeline?days=14"), api<Insight[]>("/api/insights"), api<ExperimentView>("/api/experiments/current")]);
    setTracking(profile); setTimeline(days); setInsights(patterns); setExperiment(current);
  }
  async function advance(days: number) {
    const current = await api<AdvanceReply>("/api/demo/advance", { method: "POST", body: { days } });
    setExperiment(current); setTracking(value => value ? { ...value, today: current.today, clock_offset_days: value.clock_offset_days + days } : value);
    setTimeline(current.timeline); setInsights(current.insights);
  }
  async function send(text: string) {
    let delivered = false;
    await action(async () => {
      const request = retry.current?.text === text ? retry.current : { text, id: crypto.randomUUID() };
      retry.current = request;
      const response = await api<ChatReply>("/api/chat", { method: "POST", body: { message: text, client_msg_id: request.id, tz: Intl.DateTimeFormat().resolvedOptions().timeZone } });
      setMessages(values => [...values, { id: request.id, role: "user", content: text }, { id: response.trace_id, role: "assistant", content: response.reply, red_flag: response.safety.red_flag }]);
      retry.current = null; setPending(response.pending_question);
      delivered = true;
      const [profile, days, patterns, current] = await Promise.all([api<Tracking>("/api/tracking"), api<Timeline>("/api/timeline?days=14"), api<Insight[]>("/api/insights"), api<ExperimentView>("/api/experiments/current")]);
      setTracking(profile); setTimeline(days); setInsights(patterns); setExperiment(current);
    }).catch(error => { if (!delivered) throw error; });
  }
  async function changeExperiment(path: string, body?: unknown) { setExperiment(await api<ExperimentView>(path, { method: "POST", body })); }
  async function saveDay(adherence: boolean, rating: number | null) {
    if (!experiment?.experiment || !experiment.today_plan) return;
    await api(`/api/experiments/${experiment.experiment.id}/days/${experiment.today_plan.date}`, { method: "PUT", body: { adherence, ...(rating === null ? {} : { outcome_value: rating }) } });
    const [current, days] = await Promise.all([api<ExperimentView>("/api/experiments/current"), api<Timeline>("/api/timeline?days=14")]);
    setExperiment(current); setTimeline(days);
  }
  async function deleteData() {
    await api("/api/me", { method: "DELETE" });
    setMessages([]); setTimeline(null); setTracking(null); setInsights([]); setExperiment(null); setPending(null); setConfirmDelete(false); setLoaded(false);
    window.location.reload();
  }

  return <>
    <header className="mx-auto max-w-[96rem] px-5 pb-9 pt-8 sm:px-9 lg:px-12"><div className="flex flex-wrap items-end justify-between gap-6"><div><p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#4f5c4c]">A personal research journal</p><h1 className="font-serif text-5xl leading-none tracking-tight">Nof1<span aria-hidden="true" className="ml-1 text-[#75816b]">.</span></h1><p className="mt-4 max-w-md text-base leading-relaxed text-[#4f5c4c]">One day at a time. A clearer picture over time.</p></div><div className="space-y-3"><p className="text-right text-sm text-[#4f5c4c]">{tracking ? `${tracking.is_demo ? "Simulated date" : "Today"} · ${tracking.today}` : "Your observations, in context"}</p><DemoControls isDemo={tracking?.is_demo ?? false} busy={busy || !loaded} remaining={experiment ? Math.max(0, experiment.progress.total - experiment.progress.day) : 0} onLoad={() => run(loadDemo)} onAdvance={days => run(() => advance(days))} /></div></div></header>
    <main className="mx-auto max-w-[96rem] px-5 pb-16 sm:px-9 lg:px-12">{error && <div className="mb-7 border-2 border-[#913f2b] bg-[#f4e5d9] px-4 py-3 text-[#622817]" role="alert">{error}</div>}<div className="grid items-start gap-12 border-t border-[#8d9e8a] pt-8 xl:grid-cols-[1.05fr_0.85fr_1fr] xl:gap-9"><ChatPane messages={messages} busy={busy} ready={loaded} pending={pending} onSend={send} /><TimelinePane timeline={timeline} /><section aria-labelledby="patterns-title" className="min-w-0"><div className="mb-6 flex items-baseline justify-between gap-2"><h2 id="patterns-title" className="font-serif text-3xl">Possible patterns</h2><span className="shrink-0 text-xs uppercase tracking-widest text-[#4f5c4c]">03 / Learn</span></div><p className="mb-6 text-sm leading-relaxed text-[#4f5c4c]">Observations can suggest a question. A structured test helps you explore it.</p>{experiment ? <ExperimentCard key={`${experiment.experiment?.id}-${experiment.today}-${experiment.today_plan?.adherence}-${experiment.today_plan?.outcome_value}`} data={experiment} busy={busy} onAccept={() => run(() => changeExperiment(`/api/experiments/${experiment.experiment?.id}/accept`))} onAbandon={() => run(() => changeExperiment(`/api/experiments/${experiment.experiment?.id}/abandon`))} onSave={(adherence, rating) => run(() => saveDay(adherence, rating))} /> : <p role="status" className="text-sm">Loading your experiment…</p>}<div className="mt-7">{insights.length ? insights.map(insight => <InsightCard key={insight.id} insight={insight} busy={busy || !!experiment?.experiment && !["completed", "abandoned"].includes(experiment.experiment.status)} onTest={insight => run(() => changeExperiment("/api/experiments", { pattern_id: insight.id }))} />) : <p className="border-t border-[#a3ad9b] py-6 text-sm leading-relaxed text-[#4f5c4c]">No possible patterns to show yet. Keep logging, or load the demo history to explore the workflow.</p>}</div></section></div>
      <footer className="mt-14 flex flex-wrap items-center justify-between gap-5 border-t border-[#a3ad9b] pt-6 text-sm text-[#4f5c4c]"><p>Small observations. Honest uncertainty.</p>{confirmDelete ? <div><p className="mb-3">Delete all of your messages and tracking data? This cannot be undone.</p><div className="flex gap-2"><button className={button} disabled={busy} onClick={() => run(deleteData)}>Confirm delete my data</button><button className={button} onClick={() => setConfirmDelete(false)}>Keep my data</button></div></div> : <button className="min-h-11 underline underline-offset-4" disabled={busy || !loaded} onClick={() => setConfirmDelete(true)}>Delete my data</button>}</footer>
    </main>
  </>;
}
