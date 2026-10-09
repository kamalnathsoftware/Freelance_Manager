"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ApiError } from "@fm/shared";
import { Sparkles, X } from "lucide-react";
import { useState } from "react";
import { Button } from "./ui/button";
import { useToast } from "./ui/toast";
import { api } from "@/lib/api";

export function AssistantPanel() {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState("");
  const [chat, setChat] = useState<{ role: string; content: string }[]>([]);
  const [brief, setBrief] = useState(false);
  const [req, setReq] = useState<Awaited<ReturnType<typeof api.extractRequirements>> | null>(null);
  const [reqText, setReqText] = useState("");
  const b = useQuery({ queryKey: ["briefing", brief], queryFn: () => api.briefing(brief), enabled: open });
  const onErr = (e: unknown) => toast(e instanceof ApiError ? e.message : "Something went wrong", "error");
  const send = useMutation({ mutationFn: (m: string) => api.assistantChat(m, chat), onSuccess: (r, m) => setChat((c) => [...c, { role: "user", content: m }, { role: "assistant", content: r.text }]), onError: onErr });
  const extract = useMutation({ mutationFn: () => api.extractRequirements({ text: reqText }), onSuccess: setReq, onError: onErr });
  const f = b.data?.facts as Record<string, unknown> | undefined;

  return (
    <>
      <Button variant="ghost" size="sm" aria-label="Open assistant" onClick={() => setOpen(true)}><Sparkles size={16} /></Button>
      {open && (
        <aside role="dialog" aria-label="AI assistant" className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-border bg-card shadow-card">
          <div className="flex items-center justify-between border-b border-border px-4 py-3"><h2 className="font-semibold">Assistant</h2><Button size="sm" variant="ghost" aria-label="Close assistant" onClick={() => setOpen(false)}><X size={16} /></Button></div>
          <div className="flex-1 space-y-4 overflow-auto p-4 text-sm">
            <section className="space-y-2"><h3 className="font-semibold">Today</h3>
              <p>{b.data?.headline ?? "Loading…"}</p>
              {f && <ul className="list-inside list-disc text-muted">
                {(f.deadlines_next_24h as { title: string }[]).slice(0, 4).map((d) => <li key={d.title}>{d.title}</li>)}
                {(f.clients_waiting as { subject: string; minutes: number }[]).slice(0, 3).map((c) => <li key={c.subject}>Client waiting {c.minutes} min: {c.subject}</li>)}
                {(f.top_new_jobs as { title: string; score: number }[]).slice(0, 3).map((j) => <li key={j.title}>New job ({j.score}%): {j.title}</li>)}
              </ul>}
              {b.data?.narrative ? <p className="rounded-xl bg-brand/5 p-2"><span className="text-xs font-medium text-brand">AI summary - </span>{b.data.narrative.text}</p>
                : <Button size="sm" variant="outline" onClick={() => setBrief(true)}>Write AI summary</Button>}</section>
            <section className="space-y-2"><h3 className="font-semibold">Extract requirements from a brief</h3>
              <textarea aria-label="Client brief" rows={4} value={reqText} onChange={(e) => setReqText(e.target.value)} placeholder="Paste a client message or brief…" className="w-full rounded-xl border border-border bg-card p-2" />
              <Button size="sm" variant="outline" disabled={!reqText.trim() || extract.isPending} onClick={() => extract.mutate()}>Extract</Button>
              {req && <div className="space-y-1 rounded-xl bg-brand/5 p-2"><p className="text-xs font-medium text-brand">AI-generated - verify before using</p><p>{req.summary}</p>
                {req.requirements.length > 0 && <><p className="font-medium">Requirements</p><ul className="list-inside list-disc">{req.requirements.map((r) => <li key={r}>{r}</li>)}</ul></>}
                {req.open_questions.length > 0 && <><p className="font-medium">Questions to ask</p><ul className="list-inside list-disc">{req.open_questions.map((r) => <li key={r}>{r}</li>)}</ul></>}
                <p className="text-muted">Deadline: {req.deadline ?? "-"} · Budget: {req.budget ?? "-"}</p></div>}</section>
            <section className="space-y-2"><h3 className="font-semibold">Ask</h3>
              <ul className="space-y-2">{chat.map((c, i) => <li key={i} className={c.role === "user" ? "text-right" : ""}><span className={`inline-block max-w-[90%] rounded-2xl px-3 py-1.5 ${c.role === "user" ? "bg-brand text-brand-fg" : "bg-border/50"}`}>{c.content}</span></li>)}</ul>
              <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (msg.trim()) { send.mutate(msg); setMsg(""); } }}>
                <input aria-label="Ask the assistant" value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="What should I do first today?" className="h-9 flex-1 rounded-xl border border-border bg-card px-3" /><Button size="sm" disabled={send.isPending}>Send</Button></form>
              <p className="text-xs text-muted">The assistant can read your summary data but cannot send messages or bids. AI answers can be wrong.</p></section>
          </div>
        </aside>
      )}
    </>
  );
}
