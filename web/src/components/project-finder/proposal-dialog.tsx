"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PROPOSAL_STATUSES, PROPOSAL_STATUS_LABEL, type PFProposal, type PFProposalInput, type ProposalStatus } from "@fm/shared";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { LEAD_SOURCES, errMsg, fieldErrors, todayStr } from "@/lib/pf";

export function ProposalDialog({ proposal, open, onClose }: { proposal?: PFProposal | null; open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const leads = useQuery({ queryKey: ["pf", "leads", { q: "", dueOnly: false }], queryFn: () => api.pfLeads(), enabled: open });
  const [f, setF] = useState<PFProposalInput>(() => proposal
    ? { title: proposal.title, lead_id: proposal.lead_id, source: proposal.source, sent_on: proposal.sent_on, amount: proposal.amount, currency: proposal.currency, status: proposal.status, replied_on: proposal.replied_on, outcome: proposal.outcome }
    : { title: "", lead_id: null, source: "", sent_on: todayStr(), amount: null, currency: "USD", status: "sent", replied_on: null, outcome: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = <K extends keyof PFProposalInput>(k: K, v: PFProposalInput[K]) => setF((x) => ({ ...x, [k]: v }));
  const done = (msg: string) => { qc.invalidateQueries({ queryKey: ["pf"] }); toast(msg); onClose(); };

  const save = useMutation({
    mutationFn: () => {
      if (!proposal) return api.pfCreateProposal(f);
      const { lead_id: _lead, ...patch } = f; // the lead link is fixed once created
      return api.pfUpdateProposal(proposal.id, patch);
    },
    onSuccess: () => done(proposal ? "Proposal updated" : "Proposal logged"),
    onError: (e) => { setErrors(fieldErrors(e)); toast(errMsg(e), "error"); },
  });
  const remove = useMutation({ mutationFn: () => api.pfDeleteProposal(proposal!.id), onSuccess: () => done("Proposal deleted"), onError: (e) => toast(errMsg(e), "error") });

  return (
    <Dialog open={open} onClose={onClose} title={proposal ? "Edit proposal" : "Log a proposal"}>
      <form onSubmit={(e) => { e.preventDefault(); setErrors({}); save.mutate(); }} className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2"><Input label="Title" value={f.title ?? ""} error={errors.title} maxLength={300} placeholder="Leave blank to use the lead's name" onChange={(e) => set("title", e.target.value)} /></div>
        <div className="space-y-1.5">
          <label htmlFor="pp-lead" className="text-sm font-medium">Lead</label>
          <select id="pp-lead" value={f.lead_id ?? ""} disabled={!!proposal} onChange={(e) => {
            const lead = leads.data?.find((l) => l.id === e.target.value);
            setF((x) => ({ ...x, lead_id: e.target.value || null, source: x.source || lead?.source || "", currency: lead?.currency || x.currency }));
          }} className="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm disabled:opacity-60">
            <option value="">(none)</option>
            {leads.data?.map((l) => <option key={l.id} value={l.id}>{l.business_name}</option>)}
          </select>
          {!proposal && <p className="text-xs text-muted">Linking a lead moves it to “Proposal sent”.</p>}
        </div>
        <div className="space-y-1.5">
          <label htmlFor="pp-src" className="text-sm font-medium">Source</label>
          <input id="pp-src" list="pp-srcs" value={f.source ?? ""} maxLength={80} onChange={(e) => set("source", e.target.value)} className="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm" />
          <datalist id="pp-srcs">{LEAD_SOURCES.map((s) => <option key={s} value={s} />)}</datalist>
        </div>
        <Input label="Sent on" type="date" value={f.sent_on ?? ""} error={errors.sent_on} max={todayStr()} onChange={(e) => set("sent_on", e.target.value || null)} />
        <div className="grid grid-cols-[1fr_5rem] gap-2">
          <Input label="Amount" type="number" min={0} step="0.01" value={f.amount ?? ""} error={errors.amount} onChange={(e) => set("amount", e.target.value === "" ? null : Number(e.target.value))} />
          <Input label="Currency" value={f.currency ?? ""} maxLength={3} error={errors.currency} onChange={(e) => set("currency", e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="pp-status" className="text-sm font-medium">Status</label>
          <select id="pp-status" value={f.status} onChange={(e) => set("status", e.target.value as ProposalStatus)} className="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm">
            {PROPOSAL_STATUSES.map((s) => <option key={s} value={s}>{PROPOSAL_STATUS_LABEL[s]}</option>)}
          </select>
        </div>
        <Input label="Replied on (optional)" type="date" value={f.replied_on ?? ""} error={errors.replied_on} onChange={(e) => set("replied_on", e.target.value || null)} />
        <div className="space-y-1.5 sm:col-span-2">
          <label htmlFor="pp-out" className="text-sm font-medium">Outcome / notes</label>
          <textarea id="pp-out" rows={3} maxLength={3000} value={f.outcome ?? ""} onChange={(e) => set("outcome", e.target.value)} placeholder="e.g. Client chose a cheaper bid; reason for the win/loss" className="w-full rounded-xl border border-border bg-card p-3 text-sm" />
        </div>
        <div className="flex flex-wrap justify-between gap-2 sm:col-span-2">
          {proposal ? <Button type="button" variant="danger" disabled={remove.isPending} onClick={() => { if (window.confirm("Delete this proposal?")) remove.mutate(); }}>Delete</Button> : <span />}
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save"}</Button>
          </div>
        </div>
      </form>
    </Dialog>
  );
}
