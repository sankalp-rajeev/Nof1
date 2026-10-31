"use client";
import { useState } from "react";
import { primary, field, type Message } from "../lib/api";

export function ChatMessage({ message }: { message: Message }) {
  const red = message.red_flag;
  const text = message.content.replace(/\[([^\]]+)\]\((?:tel|sms):[^)]+\)/g, "$1");
  return <article aria-label={red ? "Urgent safety reply" : message.role === "user" ? "Your message" : "Nof1 reply"} role={red ? "alert" : undefined} className={red ? "border-4 border-double border-[#3e0e0e] bg-[#761a1a] p-4 text-[#fff6e8]" : message.role === "user" ? "ml-7 border border-[#c8cebc] bg-[#e9ecdf] p-4" : "mr-5 border-l border-[#a3ad9b] py-1 pl-4"}><p className={red ? "mb-2 text-sm font-bold uppercase tracking-wide" : "mb-2 text-xs font-semibold uppercase tracking-wider text-[#4f5c4c]"}>{red ? "Urgent · act now" : message.role === "user" ? "You" : "Nof1"}</p><p className="whitespace-pre-wrap text-base leading-relaxed">{text}</p></article>;
}

export function ChatPane({ messages, busy, ready, pending, onSend }: { messages: Message[]; busy: boolean; ready: boolean; pending: string | null; onSend: (text: string) => Promise<void> }) {
  const [text, setText] = useState("");
  return <section aria-labelledby="chat-title" className="min-w-0"><div className="mb-6 flex items-baseline justify-between"><h2 id="chat-title" className="font-serif text-3xl">Your daily notes</h2><span className="text-xs uppercase tracking-widest text-[#4f5c4c]">01 / Chat</span></div>
    <div className="space-y-5 overflow-y-auto pr-1 sm:max-h-[32rem]" aria-live="polite">{messages.length ? messages.map(message => <ChatMessage key={message.id} message={message} />) : <div className="py-9"><p className="font-serif text-2xl leading-snug">Start with what today felt like.</p><p className="mt-4 max-w-sm text-base leading-relaxed text-[#4f5c4c]">Tell Nof1 what you’d like to track. A short note is enough; you’ll be asked one question at a time.</p></div>}{busy && <p role="status" className="text-sm text-[#4f5c4c]">Working on your check-in…</p>}</div>
    {pending && <p className="mt-5 border-t border-[#c8cebc] pt-4 text-sm leading-relaxed"><span className="font-semibold">Next question: </span>{pending}</p>}
    <form className="mt-6" onSubmit={async event => { event.preventDefault(); if (!text.trim()) return; try { await onSend(text.trim()); setText(""); } catch { /* Parent retains a safe, visible error and this draft. */ } }}><label htmlFor="daily-note" className="text-sm font-semibold">A note about your day</label><textarea id="daily-note" className={field + " mt-2 min-h-28 resize-y"} placeholder="What happened, what you had, how you felt…" value={text} maxLength={20000} onChange={event => setText(event.target.value)} disabled={busy || !ready} /><div className="mt-3 flex items-center justify-between gap-4"><p className="max-w-44 text-xs leading-relaxed text-[#4f5c4c]">For self-tracking. If this is urgent, contact emergency services.</p><button className={primary} disabled={busy || !ready || !text.trim()}>{busy ? "Sending…" : "Send note"}</button></div></form>
  </section>;
}
