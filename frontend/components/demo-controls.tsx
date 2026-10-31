"use client";
import { button } from "../lib/api";
export function DemoControls({ isDemo, busy, remaining, onLoad, onAdvance }: { isDemo: boolean; busy: boolean; remaining: number; onLoad: () => void; onAdvance: (days: number) => void }) {
  return <div className="flex flex-wrap items-center gap-2">{isDemo ? <><span className="mr-1 text-xs font-semibold uppercase tracking-widest">Simulated history</span><button className={button} disabled={busy} onClick={() => onAdvance(1)}>Next day <span className="sr-only">(simulated)</span></button>{remaining > 0 && <button className={button} disabled={busy} onClick={() => onAdvance(Math.min(14, remaining))}>Skip to end <span className="sr-only">(simulated)</span></button>}</> : <button className={button} disabled={busy} onClick={onLoad}>Load demo history</button>}</div>;
}
