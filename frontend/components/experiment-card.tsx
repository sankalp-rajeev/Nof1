"use client";
import { useState } from "react";
import { button, primary, field, dateLabel, type ExperimentView, type Phase } from "../lib/api";

export function PhaseLabel({ phase }: { phase: Phase }) {
  const shape = phase === "on" ? "rounded-full bg-[#214b39]" : phase === "off" ? "rotate-45 border-2 border-[#214b39] bg-[repeating-linear-gradient(135deg,transparent,transparent_3px,#214b39_3px,#214b39_4px)]" : "border-2 border-[#214b39]";
  return <div className="flex items-center gap-4"><span aria-hidden="true" className={`h-5 w-5 shrink-0 ${shape}`} /><strong className="font-serif text-3xl font-normal tracking-wide">{phase.toUpperCase()}</strong></div>;
}

export function ExperimentCard({ data, busy, onAccept, onAbandon, onSave }: { data: ExperimentView; busy: boolean; onAccept: () => void; onAbandon: () => void; onSave: (adherence: boolean, rating: number | null) => void }) {
  const [adherence, setAdherence] = useState<boolean | null>(data.today_plan?.adherence ?? null);
  const [rating, setRating] = useState(data.today_plan?.outcome_value?.toString() ?? "");
  const [confirmAbandon, setConfirmAbandon] = useState(false);
  const experiment = data.experiment;
  if (!experiment) return <section className="border border-[#a3ad9b] bg-[#edeee3] p-5 sm:p-6"><p className="text-xs font-semibold uppercase tracking-widest text-[#4f5c4c]">Personal experiment</p><h3 className="mt-3 font-serif text-2xl">A question worth testing.</h3><p className="mt-3 text-sm leading-relaxed">When a possible pattern appears, you can review a structured on/off experiment here.</p></section>;
  const verdict = experiment.verdict;
  if (verdict) {
    const label = { helped: "Helped in this test", worsened: "Worsened in this test", no_detectable_effect: "No detectable effect", inconclusive: "Inconclusive" }[verdict.label];
    return <section className="border-2 border-[#6f7c6b] bg-[#edeee3] p-5 sm:p-6" aria-label="Experiment verdict"><p className="mb-4 text-xs font-semibold uppercase tracking-widest">Experiment result</p><h3 className="text-base font-semibold">{label}</h3><p className="mt-3 text-base">Usable data: {verdict.n_on} ON days and {verdict.n_off} OFF days.</p><p className="mt-3 text-base leading-relaxed">{data.limitation}</p>{verdict.benefit !== null && <p className="mt-3 text-base">Estimated benefit: {verdict.benefit.toFixed(1)} points.{verdict.ci_low !== null && verdict.ci_high !== null ? ` Interval: ${verdict.ci_low.toFixed(1)} to ${verdict.ci_high.toFixed(1)}.` : ""}</p>}<p className="mt-4 text-base">This is not medical advice.</p></section>;
  }
  if (experiment.status === "abandoned") return <section className="border border-[#a3ad9b] p-5"><h3 className="font-serif text-2xl">Experiment closed</h3><p className="mt-3">Your existing records remain in the timeline.</p></section>;
  const validRating = rating === "" || (/^\d+$/.test(rating) && Number(rating) >= 0 && Number(rating) <= 10);
  return <section className="border border-[#83927e] bg-[#edeee3] p-5 sm:p-6" aria-label="Current experiment"><p className="text-xs font-semibold uppercase tracking-widest">Your personal experiment</p><h3 className="mt-3 font-serif text-2xl">{experiment.exposure} &amp; {experiment.outcome}</h3>
    {experiment.status === "proposed" ? <><p className="mt-4 leading-relaxed">Review a 14-day test: usual routine during BASELINE, followed by alternating ON and OFF blocks. The first day of each block is a washout day and is not counted.</p><p className="mt-3 text-sm">The schedule begins tomorrow if you accept. This small, unblinded experiment is for self-tracking.</p><button disabled={busy} onClick={onAccept} className={primary + " mt-5"}>Accept this plan</button></> : <>
      <div className="mt-5 flex justify-between text-sm"><span>Experiment progress</span><span>Day {data.progress.day} of {data.progress.total}</span></div><progress aria-label="Experiment progress" className="mt-2 h-2 w-full accent-[#214b39]" max={data.progress.total || 14} value={data.progress.day} />
      {data.today_plan ? <><div className="mt-6"><PhaseLabel phase={data.today_plan.phase} /></div><p className="mt-3">{data.today_plan.phase === "baseline" ? "Keep your usual routine." : "Follow your accepted plan."}</p>{data.today_plan.washout && <p className="mt-2 border border-dashed border-[#718175] px-3 py-2 text-sm">Washout · This day is not counted.</p>}
        <form className="mt-6 space-y-4" onSubmit={event => { event.preventDefault(); const answer = data.today_plan?.phase === "baseline" ? true : adherence; if (answer !== null && validRating) onSave(answer, rating === "" ? null : Number(rating)); }}>
          {data.today_plan.phase !== "baseline" && <fieldset><legend className="mb-2 text-sm font-semibold">Did you follow today’s accepted plan?</legend><div className="flex gap-2">{([true, false] as const).map(value => <button key={String(value)} type="button" className={adherence === value ? primary : button} aria-pressed={adherence === value} onClick={() => setAdherence(value)}>{value ? "Yes" : "No"}</button>)}</div></fieldset>}
          <label className="block text-sm font-semibold">{experiment.outcome} rating (0–10)<input aria-label={`${experiment.outcome} rating (0–10)`} className={field + " mt-2"} type="number" min={0} max={10} step={1} value={rating} onChange={event => setRating(event.target.value)} /></label>
          <button className={primary} disabled={busy || !validRating || (adherence === null && data.today_plan.phase !== "baseline")} type="submit">{busy ? "Saving…" : "Save today’s entry"}</button>
        </form></> : <p className="mt-4">Your accepted test starts {experiment.started_on ? dateLabel(experiment.started_on) : "tomorrow"}. Keep your usual routine until then.</p>}
    </>}
    <div className="mt-6 border-t border-[#b9c1ad] pt-4">{confirmAbandon ? <><p className="mb-3 text-sm">Close this experiment? Its records will remain.</p><div className="flex gap-2"><button className={button} disabled={busy} onClick={onAbandon}>Confirm abandon</button><button className={button} onClick={() => setConfirmAbandon(false)}>Keep experiment</button></div></> : <button className="min-h-11 text-sm underline underline-offset-4" disabled={busy} onClick={() => setConfirmAbandon(true)}>Abandon experiment</button>}</div>
  </section>;
}
