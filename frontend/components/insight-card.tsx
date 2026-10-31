"use client";
import { useState } from "react";
import { button, dateLabel, type Insight } from "../lib/api";

export function InsightCard({ insight, busy, onTest }: { insight: Insight; busy: boolean; onTest: (insight: Insight) => void }) {
  const [expanded, setExpanded] = useState(false);
  return <article className="border-t border-[#a3ad9b] py-6">
    <div className="flex items-start justify-between gap-3"><h3 className="font-serif text-2xl leading-tight">{insight.exposure} <span className="text-[#526050]">&amp;</span> {insight.outcome}</h3><span className="shrink-0 border border-[#8d9e8a] px-2 py-1 text-xs font-semibold uppercase tracking-wider">{insight.tier}</span></div>
    <p className="mt-4 leading-relaxed">Possible pattern: {insight.exposure} days were associated with {Math.abs(insight.effect).toFixed(1)} points {insight.effect < 0 ? "lower" : "higher"} {insight.outcome}{insight.lag_days ? ` after ${insight.lag_days} day${insight.lag_days === 1 ? "" : "s"}` : " on the same day"}.</p>
    <p className="mt-2 text-sm text-[#4f5c4c]">{insight.n_pairs} paired days · {insight.n_exposed} with / {insight.n_unexposed} without</p>
    {insight.confounder && <p className="mt-4 border border-[#917c45] bg-[#f1ead4] p-3 text-sm text-[#53431d]">Another factor, {insight.confounder}, may help explain this pattern.</p>}
    <div className="mt-5 flex flex-wrap gap-2"><button className={button} aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? "Hide data points" : "Show data points"}</button>{insight.eligible && <button disabled={busy} onClick={() => onTest(insight)} className={button}>Test this</button>}</div>
    {expanded && <div className="mt-4 overflow-x-auto"><table className="w-full text-left text-sm"><caption className="mb-3 text-left text-[#4f5c4c]">Frozen evidence for this possible pattern.</caption><thead className="border-b border-[#a3ad9b]"><tr><th className="py-2 pr-2 font-medium">Exposure day</th><th className="py-2 pr-2 font-medium">Status</th><th className="py-2 pr-2 font-medium">Rating day</th><th className="py-2 font-medium">Rating</th></tr></thead><tbody>{insight.data_points.map((point, index) => <tr key={index} className="border-b border-[#d8dbcb]"><td className="py-2 pr-2">{dateLabel(point.exposure_date)}</td><td className="py-2 pr-2">{point.x ? "Done" : "Skipped"}</td><td className="py-2 pr-2">{dateLabel(point.outcome_date)}</td><td className="py-2">{point.y}</td></tr>)}</tbody></table></div>}
  </article>;
}
