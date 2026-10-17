"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PROPOSAL_STATUSES, PROPOSAL_STATUS_LABEL, type PFProposal, type ProposalStatus } from "@fm/shared";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, Skeleton } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { ProposalDialog } from "@/components/project-finder/proposal-dialog";
import { api } from "@/lib/api";
import { errMsg } from "@/lib/pf";
import { cn } from "@/lib/utils";

const TONE: Record<ProposalStatus, string> = {
  sent: "border-border text-muted", replied: "border-brand text-brand", interview: "border-brand text-brand",
  won: "border-success text-success", lost: "border-danger text-danger", no_response: "border-border text-muted",
};
const STALE_DAYS = 7;

export default function ProposalsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [status, setStatus] = useState<ProposalStatus | "">("");
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<PFProposal | "new" | null>(null);
  const list = useQuery({ queryKey: ["pf", "proposals", { status, q }], queryFn: () => api.pfProposals({ status, q }) });
  const all = useQuery({ queryKey: ["pf", "proposals", { status: "", q: "" }], queryFn: () => api.pfProposals() });
  const counts = (s: ProposalStatus) => all.data?.filter((p) => p.status === s).length ?? 0;
  const setStat = useMutation({
    mutationFn: ({ id, s }: { id: string; s: ProposalStatus }) => api.pfUpdateProposal(id, { status: s }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pf"] }),
    onError: (e) => toast(errMsg(e), "error"),
  });
  const stale = all.data?.filter((p) => p.status === "sent" && (p.days_waiting ?? 0) >= STALE_DAYS).length ?? 0;

  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-end gap-3">
        <div className="min-w-[10rem] flex-1"><Input label="Search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="title or outcome…" /></div>
        <Button onClick={() => setEditing("new")}><Plus size={16} /> Log proposal</Button>
        <div className="flex w-full flex-wrap gap-1.5" role="group" aria-label="Filter by status">
          <Button size="sm" variant={status === "" ? "primary" : "outline"} aria-pressed={status === ""} onClick={() => setStatus("")}>All{all.data ? ` (${all.data.length})` : ""}</Button>
          {PROPOSAL_STATUSES.map((s) => <Button key={s} size="sm" variant={status === s ? "primary" : "outline"} aria-pressed={status === s} onClick={() => setStatus(s)}>{PROPOSAL_STATUS_LABEL[s]} ({counts(s)})</Button>)}
        </div>
      </Card>
      {stale > 0 && !status && <p role="status" className="rounded-xl border border-border px-3 py-2 text-sm text-muted">{stale} proposal{stale > 1 ? "s have" : " has"} had no reply for {STALE_DAYS}+ days - worth a polite follow-up.</p>}

      {list.isLoading && <Skeleton className="h-40" />}
      {list.isError && <Card role="alert" className="text-sm text-danger">Could not load proposals. <button className="underline" onClick={() => list.refetch()}>Retry</button></Card>}
      {list.data?.length === 0 && (
        q || status ? <EmptyState title="No proposals match" hint="Try another status or clear the search." />
          : <EmptyState title="No proposals logged yet" hint="Log every proposal you send - amount, date and what happened - and Stats will show your reply rate, win rate and best source."
              action={<Button onClick={() => setEditing("new")}><Plus size={16} /> Log your first proposal</Button>} />
      )}
      <ul className="grid gap-3 md:grid-cols-2">
        {list.data?.map((p) => (
          <li key={p.id}>
            <Card className="flex h-full flex-col gap-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <button className="text-left font-semibold hover:text-brand" onClick={() => setEditing(p)}>{p.title}</button>
                  <p className="text-xs text-muted">
                    {p.lead_id ? <Link href={`/project-finder/leads?lead=${p.lead_id}`} className="underline">{p.lead_name || "Lead"}</Link> : "No lead"}{p.source && ` · ${p.source}`} · sent {p.sent_on}
                  </p>
                </div>
                {p.amount != null && <span className="shrink-0 font-semibold">{p.currency} {p.amount.toLocaleString()}</span>}
              </div>
              {p.outcome && <p className="line-clamp-2 text-sm text-muted">{p.outcome}</p>}
              <div className="mt-auto flex flex-wrap items-center gap-2">
                <span className={cn("rounded-full border px-2 py-0.5 text-xs", TONE[p.status])}>{PROPOSAL_STATUS_LABEL[p.status]}</span>
                {p.replied_on && <span className="text-xs text-muted">replied {p.replied_on}</span>}
                {p.days_waiting != null && p.days_waiting >= STALE_DAYS && <span className="text-xs text-danger">waiting {p.days_waiting} days</span>}
                <label className="sr-only" htmlFor={`st-${p.id}`}>Status of {p.title}</label>
                <select id={`st-${p.id}`} value={p.status} onChange={(e) => setStat.mutate({ id: p.id, s: e.target.value as ProposalStatus })} className="ml-auto h-8 rounded-lg border border-border bg-card px-1 text-xs">
                  {PROPOSAL_STATUSES.map((s) => <option key={s} value={s}>{PROPOSAL_STATUS_LABEL[s]}</option>)}
                </select>
              </div>
            </Card>
          </li>
        ))}
      </ul>
      {editing && <ProposalDialog key={editing === "new" ? "new" : editing.id} proposal={editing === "new" ? null : editing} open onClose={() => setEditing(null)} />}
    </div>
  );
}
