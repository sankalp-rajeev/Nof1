export interface ApiProblem { error: { code: string; message: string } }
export class ApiError extends Error {
  constructor(public readonly code: string, message: string, public readonly status: number) { super(message); }
}
function problem(value: unknown): value is ApiProblem {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = value.error;
  return typeof error === "object" && error !== null && "code" in error && typeof error.code === "string" && "message" in error && typeof error.message === "string";
}
export async function api<T>(path: string, options: { method?: string; body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { method: options.method ?? "GET", credentials: "include", headers: options.body === undefined ? undefined : { "Content-Type": "application/json" }, body: options.body === undefined ? undefined : JSON.stringify(options.body), signal: options.signal });
  } catch {
    throw new ApiError("connection", "Couldn’t reach Nof1. Please try again.", 0);
  }
  let data: unknown;
  try { data = await response.json(); } catch { throw new ApiError("invalid_response", "The service returned an unreadable response.", response.status); }
  if (!response.ok) throw new ApiError(problem(data) ? data.error.code : "request", problem(data) ? data.error.message : "The request could not be completed.", response.status);
  return data as T;
}

export interface Tracking { outcomes: { name: string; direction_better: "lower" | "higher" }[]; exposures: { name: string }[]; track_sleep: boolean; is_demo: boolean; today: string; clock_offset_days: number }
export interface Message { id: string; role: "user" | "assistant"; content: string; red_flag?: boolean }
export interface Event { id: string; name: string; kind: string; status: "done" | "skipped"; value: number | null; severity: number | null }
export interface TimelineDay { date: string; events: Event[]; ratings: { outcome_name: string; value: number }[]; checklist_answered: boolean; completed: boolean }
export interface Timeline { today: string; days: TimelineDay[] }
export interface EvidencePoint { outcome_date: string; exposure_date: string; x: number; y: number }
export interface Insight { id: string; exposure: string; outcome: string; lag_days: number; tier: "weak" | "moderate"; effect: number; n_pairs: number; n_exposed: number; n_unexposed: number; confounder: string | null; data_points: EvidencePoint[]; eligible: boolean; ineligible_reason: string | null }
export type Phase = "baseline" | "on" | "off";
export interface Verdict { label: "helped" | "worsened" | "no_detectable_effect" | "inconclusive"; n_on: number; n_off: number; benefit: number | null; ci_low: number | null; ci_high: number | null }
export interface Experiment { id: string; exposure: string; outcome: string; status: "proposed" | "accepted" | "baseline" | "running" | "completed" | "abandoned"; started_on: string | null; protocol: { baseline_days: number; block_days: number; n_blocks: number; washout_days: number }; verdict: Verdict | null }
export interface ExperimentView { experiment: Experiment | null; today: string; today_plan: { date: string; phase: Phase; washout: boolean; adherence: boolean | null; outcome_value: number | null } | null; progress: { day: number; total: number }; schedule: { date: string; phase: Phase; washout: boolean }[]; limitation: string }
export interface ChatReply { reply: string; events_logged: Event[]; pending_question: string | null; safety: { red_flag: boolean }; limited_mode: boolean; trace_id: string }
export interface AdvanceReply extends ExperimentView { timeline: Timeline; insights: Insight[] }
export const button = "inline-flex min-h-11 items-center justify-center border border-[#718175] px-4 py-2 text-sm font-semibold transition-colors hover:bg-[#e6e7db] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#214b39] disabled:cursor-wait disabled:border-dashed";
export const primary = button + " border-[#214b39] bg-[#214b39] text-[#faf7ee] hover:bg-[#153c2b]";
export const field = "min-h-11 w-full border border-[#718175] bg-[#fbf8f0] px-3 py-2 text-base text-[#193d2f] placeholder:text-[#526050] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#214b39]";
export function dateLabel(date: string): string { return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", timeZone: "UTC" }).format(new Date(date + "T12:00:00Z")); }
