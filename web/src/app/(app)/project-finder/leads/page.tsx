"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LEAD_STATUSES, LEAD_STATUS_LABEL, type LeadStatus, type PFLead } from "@fm/shared";
import { CalendarClock, Globe, LayoutGrid, List, Plus, Send } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, Skeleton } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { GoalCard } from "@/components/project-finder/goal-card";
import { LeadDialog } from "@/components/project-finder/lead-form";
import { api } from "@/lib/api";
import { errMsg } from "@/lib/pf";
import { cn } from "@/lib/utils";

export default function LeadsPage() {
  return <Suspense fallback={<Skeleton className="h-64" />}><Leads /></Suspense>;
}

function Leads() {
  const qc = useQueryClient();
  const toast = useToast();
  const params = useSearchParams();
  const [view, setView] = useState<"board" | "list">("board");
  const [q, setQ] = useState("");
  const [dueOnly, setDueOnly] = useState(false);
  const [editing, setEditing] = useState<PFLead | "new" | null>(null);
  const [over, setOver] = useState<LeadStatus | null>(null);
  const key = ["pf", "leads", { q, dueOnly }];
  const leads = useQuery({ queryKey: key, queryFn: () => api.pfLeads({ q, due: dueOnly }) });
  const deepLinked = params.get("lead");
  const target = editing ?? (deepLinked ? leads.data?.find((l) => l.id === deepLinked) ?? null : null);

  const move = useMutation({
    mutationFn: ({ id, status }: { id: string; status: LeadStatus }) => api.pfUpdateLead(id, { status }),
    onMutate: async ({ id, status }) => {
      await qc.cancelQueries({ queryKey: ["pf", "leads"] });
      const prev = qc.getQueryData<PFLead[]>(key);
      qc.setQueryData<PFLead[]>(key, (old) => old?.map((l) => (l.id === id ? { ...l, status } : l)));
      return { prev };
    },
    onError: (e, _v, ctx) => { qc.setQueryData(key, ctx?.prev); toast(errMsg(e, "Could not move lead"), "error"); },
    onSettled: () => { qc.invalidateQueries({ queryKey: ["pf", "leads"] }); qc.invalidateQueries({ queryKey: ["pf", "goal"] }); },
  });
  const logSent = useMutation({
    mutationFn: (id: string) => api.pfLogOutreach({ lead_id: id }),
    onSuccess: () => { toast("Logged - remember to send it yourself"); qc.invalidateQueries({ queryKey: ["pf"] }); },
    onError: (e) => toast(errMsg(e), "error"),
  });

  const by = (s: LeadStatus) => leads.data?.filter((l) => l.status === s) ?? [];
  const dueCount = leads.data?.filter((l) => l.follow_up_due).length ?? 0;

  const card = (l: PFLead) => (
    <li key={l.id} draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", l.id)}
      className="cursor-grab space-y-2 rounded-xl border border-border bg-card p-3 text-sm shadow-card active:cursor-grabbing">
      <button className="text-left font-medium hover:text-brand" onClick={() => setEditing(l)}>{l.business_name}</button>
      {l.contact_name && <p className="text-xs text-muted">{l.contact_name}</p>}
      {l.problem && <p className="line-clamp-2 text-xs text-muted">{l.problem}</p>}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {l.next_follow_up && <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5", l.follow_up_due ? "border-danger text-danger" : "border-border text-muted")}><CalendarClock size={12} aria-hidden />{l.follow_up_due ? "Due " : ""}{l.next_follow_up}</span>}
        {l.country && <span className="inline-flex items-center gap-1 text-muted"><Globe size={12} aria-hidden />{l.country}</span>}
      </div>
      <div className="flex items-center gap-2">
        {/* keyboard- and touch-accessible alternative to drag and drop */}
        <select aria-label={`Status of ${l.business_name}`} value={l.status} onChange={(e) => move.mutate({ id: l.id, status: e.target.value as LeadStatus })} className="h-8 min-w-0 flex-1 rounded-lg border border-border bg-card px-1 text-xs">
          {LEAD_STATUSES.map((s) => <option key={s} value={s}>{LEAD_STATUS_LABEL[s]}</option>)}
        </select>
        <Button size="sm" variant="outline" aria-label={`Log message sent to ${l.business_name}`} title="Log a message you sent" disabled={logSent.isPending} onClick={() => logSent.mutate(l.id)}><Send size={12} /></Button>
      </div>
    </li>
  );

  return (
    <div className="space-y-4">
      <GoalCard />
      <Card className="flex flex-wrap items-end gap-3">
        <div className="min-w-[10rem] flex-1"><Input label="Search leads" value={q} onChange={(e) => setQ(e.target.value)} placeholder="business, contact, problem…" /></div>
        <label className="flex h-10 items-center gap-2 text-sm"><input type="checkbox" checked={dueOnly} onChange={(e) => setDueOnly(e.target.checked)} /> Follow-up due{dueCount > 0 && !dueOnly ? ` (${dueCount})` : ""}</label>
        <div className="flex gap-1" role="group" aria-label="View">
          <Button variant={view === "board" ? "primary" : "outline"} size="md" aria-pressed={view === "board"} aria-label="Board view" onClick={() => setView("board")}><LayoutGrid size={16} /></Button>
          <Button variant={view === "list" ? "primary" : "outline"} size="md" aria-pressed={view === "list"} aria-label="List view" onClick={() => setView("list")}><List size={16} /></Button>
        </div>
        <Button onClick={() => setEditing("new")}><Plus size={16} /> Add lead</Button>
      </Card>

      {leads.isLoading && <Skeleton className="h-64" />}
      {leads.isError && <Card role="alert" className="text-sm text-danger">Could not load leads. <button className="underline" onClick={() => leads.refetch()}>Retry</button></Card>}
      {leads.data?.length === 0 && (
        <EmptyState title={q || dueOnly ? "No leads match" : "No leads yet"} hint={q || dueOnly ? "Try clearing the search or the follow-up filter." : "Add businesses you've noticed a problem for, then work them across the board. Your goal: 5 outreach messages a day."}
          action={!q && !dueOnly ? <Button onClick={() => setEditing("new")}><Plus size={16} /> Add your first lead</Button> : undefined} />
      )}

      {!!leads.data?.length && view === "board" && (
        <div className="-mx-4 flex gap-3 overflow-x-auto px-4 pb-4 md:mx-0 md:px-0">
          {LEAD_STATUSES.map((s) => (
            <section key={s} aria-label={LEAD_STATUS_LABEL[s]} onDragOver={(e) => { e.preventDefault(); setOver(s); }} onDragLeave={() => setOver(null)}
              onDrop={(e) => { e.preventDefault(); setOver(null); const id = e.dataTransfer.getData("text/plain"); if (id && leads.data?.find((l) => l.id === id)?.status !== s) move.mutate({ id, status: s }); }}
              className={cn("w-64 shrink-0 rounded-2xl border border-border bg-card/60 p-3 transition-colors", over === s && "border-brand bg-brand/5")}>
              <h2 className="mb-2 flex justify-between text-sm font-semibold">{LEAD_STATUS_LABEL[s]}<span className="text-muted">{by(s).length}</span></h2>
              <ul className="space-y-2">{by(s).map(card)}</ul>
            </section>
          ))}
        </div>
      )}

      {!!leads.data?.length && view === "list" && <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{leads.data.map(card)}</ul>}

      {target && <LeadDialog key={target === "new" ? "new" : target.id} lead={target === "new" ? null : target} open onClose={() => { setEditing(null); if (deepLinked) window.history.replaceState(null, "", "/project-finder/leads"); }} />}
    </div>
  );
}
