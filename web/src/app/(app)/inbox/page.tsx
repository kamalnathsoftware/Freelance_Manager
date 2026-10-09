"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, type SendResult } from "@fm/shared";
import { Clock, Copy, ExternalLink, Sparkles, Star } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { PlatformBadge } from "@/components/platform-badge";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, Skeleton } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const ago = (iso: string) => {
  const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  return m < 60 ? `${m}m` : m < 1440 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`;
};

export default function Inbox() {
  const qc = useQueryClient();
  const toast = useToast();
  const [status, setStatus] = useState<"open" | "snoozed" | "archived">("open");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [aiDraft, setAiDraft] = useState(false);
  const [manual, setManual] = useState<SendResult | null>(null);
  const idem = useRef<string>(crypto.randomUUID());
  const onErr = (e: unknown) => toast(e instanceof ApiError ? e.message : "Something went wrong", "error");

  const convs = useQuery({ queryKey: ["conversations", status, unreadOnly, q], queryFn: () => api.conversations({ status, unread: unreadOnly, q }) });
  const sla = useQuery({ queryKey: ["sla"], queryFn: api.slaAlerts, refetchInterval: 60_000 });
  const canned = useQuery({ queryKey: ["canned"], queryFn: api.canned });
  const msgs = useQuery({ queryKey: ["messages", sel], queryFn: () => api.messages(sel!), enabled: !!sel });
  const current = convs.data?.find((c) => c.id === sel);
  useEffect(() => { if (!sel && convs.data?.length) setSel(convs.data[0].id); }, [convs.data, sel]);

  const refresh = () => ["conversations", "unread", "sla"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const patch = useMutation({ mutationFn: (b: Parameters<typeof api.patchConversation>[1]) => api.patchConversation(sel!, b), onSuccess: refresh, onError: onErr });
  const send = useMutation({
    mutationFn: () => api.sendMessage(sel!, { body: draft, idempotency_key: idem.current, ai_generated: aiDraft, approved: aiDraft }),
    onSuccess: (r) => {
      setDraft(""); setAiDraft(false); idem.current = crypto.randomUUID();
      setManual(r.requires_manual_paste ? r : null);
      qc.invalidateQueries({ queryKey: ["messages", sel] }); refresh();
    },
    onError: onErr,
  });
  const confirm = useMutation({ mutationFn: (id: string) => api.confirmSent(id), onSuccess: () => { setManual(null); qc.invalidateQueries({ queryKey: ["messages", sel] }); refresh(); toast("Marked as sent"); }, onError: onErr });
  const suggest = useMutation({ mutationFn: () => api.suggestReply(sel!), onSuccess: (s) => { setDraft(s.text); setAiDraft(true); }, onError: onErr });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold">Inbox</h1>
        {!!sla.data?.alerts.length && (
          <p role="status" className="rounded-xl bg-danger/10 px-3 py-1.5 text-sm text-danger">
            <Clock size={14} className="mr-1 inline" />{sla.data.alerts[0].vip && "VIP "}client waiting {sla.data.alerts[0].waiting_minutes} min
            {sla.data.alerts.length > 1 && ` (+${sla.data.alerts.length - 1} more)`}
          </p>
        )}
      </div>
      <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
        <Card className="space-y-3 p-3">
          <input aria-label="Search conversations" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} className="h-9 w-full rounded-xl border border-border bg-card px-3 text-sm" />
          <div className="flex gap-1 text-sm" role="tablist">
            {(["open", "snoozed", "archived"] as const).map((s) => (
              <button key={s} role="tab" aria-selected={status === s} onClick={() => { setStatus(s); setSel(null); }} className={cn("rounded-lg px-2 py-1 capitalize", status === s ? "bg-brand/10 text-brand" : "text-muted")}>{s}</button>
            ))}
            <label className="ml-auto flex items-center gap-1 text-xs text-muted"><input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} /> Unread</label>
          </div>
          {convs.isLoading && <Skeleton className="h-24" />}
          {convs.data?.length === 0 && <EmptyState title="Nothing here" hint="Messages from connected platforms, forwarded emails and the extension show up here." />}
          <ul className="max-h-[60vh] space-y-1 overflow-auto">
            {convs.data?.map((c) => (
              <li key={c.id}>
                <button onClick={() => { setSel(c.id); setManual(null); }} className={cn("w-full rounded-xl p-2.5 text-left text-sm hover:bg-border/40", sel === c.id && "bg-brand/10")}>
                  <div className="flex items-center justify-between gap-2">
                    <PlatformBadge platform={c.platform} />
                    <span className="text-xs text-muted">{ago(c.last_message_at)}</span>
                  </div>
                  <p className={cn("mt-1 truncate", c.unread_count > 0 && "font-semibold")}>{c.client_name || c.subject}{c.client_vip && " ★"}</p>
                  <p className="truncate text-xs text-muted">{c.last_preview}</p>
                  {c.unread_count > 0 && <span className="mt-1 inline-block rounded-full bg-brand px-1.5 text-xs text-brand-fg">{c.unread_count}</span>}
                </button>
              </li>
            ))}
          </ul>
        </Card>
        <Card className="flex min-h-[60vh] flex-col gap-3">
          {!current ? <EmptyState title="Select a conversation" hint="Pick a thread on the left to read and reply." /> : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div><h2 className="font-semibold">{current.subject}</h2><p className="text-xs text-muted">{current.client_name}</p></div>
                <div className="flex gap-1">
                  <Button size="sm" variant="ghost" aria-label="Star" onClick={() => patch.mutate({ starred: !current.starred })}><Star size={14} className={current.starred ? "fill-current text-brand" : ""} /></Button>
                  <Button size="sm" variant="outline" onClick={() => patch.mutate({ snooze_minutes: 60 })}>Snooze 1h</Button>
                  <Button size="sm" variant="outline" onClick={() => patch.mutate({ status: current.status === "archived" ? "open" : "archived" })}>{current.status === "archived" ? "Unarchive" : "Archive"}</Button>
                </div>
              </div>
              <ul className="flex-1 space-y-2 overflow-auto" aria-live="polite">
                {msgs.data?.map((m) => (
                  <li key={m.id} className={cn("max-w-[80%] rounded-2xl px-3 py-2 text-sm", m.direction === "out" ? "ml-auto bg-brand text-brand-fg" : "bg-border/50")}>
                    <p className="whitespace-pre-wrap">{m.body}</p>
                    <p className="mt-1 text-[11px] opacity-70">
                      {new Date(m.created_at).toLocaleString()}{m.ai_generated && " · AI-assisted"}{m.delivery === "pending_manual" && " · waiting for you to paste on platform"}
                    </p>
                    {m.delivery === "pending_manual" && <button className="mt-1 text-xs underline" onClick={() => confirm.mutate(m.id)}>I sent it</button>}
                  </li>
                ))}
              </ul>
              {manual && (
                <div className="space-y-2 rounded-xl border border-border p-3 text-sm">
                  <p>This platform has no messaging API, so paste your reply there yourself.</p>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="outline" onClick={async () => { await navigator.clipboard.writeText(manual.message.body); toast("Copied"); }}><Copy size={14} /> Copy reply</Button>
                    {manual.reply_on_platform_url && <a href={manual.reply_on_platform_url} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1 rounded-xl border border-border px-3 hover:bg-border/40"><ExternalLink size={14} /> Reply on platform</a>}
                    <Button size="sm" onClick={() => confirm.mutate(manual.message.id)}>I sent it</Button>
                  </div>
                </div>
              )}
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <select aria-label="Quick reply" defaultValue="" onChange={(e) => { const c = canned.data?.find((x) => x.id === e.target.value); if (c) setDraft(c.body); e.target.value = ""; }} className="h-8 rounded-xl border border-border bg-card px-2 text-sm">
                    <option value="" disabled>Quick reply…</option>
                    {canned.data?.map((c) => <option key={c.id} value={c.id}>{c.shortcut}</option>)}
                  </select>
                  <Button size="sm" variant="outline" disabled={suggest.isPending} onClick={() => suggest.mutate()}><Sparkles size={14} /> Suggest reply</Button>
                  {aiDraft && <span className="rounded-full bg-brand/10 px-2 py-0.5 text-xs text-brand">AI draft - edit and review before sending</span>}
                </div>
                <textarea aria-label="Reply" rows={3} value={draft} onChange={(e) => setDraft(e.target.value)} className="w-full rounded-xl border border-border bg-card p-3 text-sm" placeholder="Write a reply…" />
                <Button disabled={!draft.trim() || send.isPending} onClick={() => send.mutate()}>Send reply</Button>
              </div>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
