"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LEAD_STATUSES, LEAD_STATUS_LABEL, type LeadStatus, type PFLead, type PFLeadInput } from "@fm/shared";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { InvoicesPanel } from "@/components/project-finder/invoices-panel";
import { OverlapPanel } from "@/components/project-finder/tz-overlap";
import { COMMON_TIMEZONES, LEAD_SOURCES, errMsg, fieldErrors } from "@/lib/pf";

const blank = (): PFLeadInput => ({
  business_name: "", contact_name: "", email: "", linkedin_url: "", website: "", problem: "", notes: "", source: "", status: "new",
  next_follow_up: null, country: "", timezone: "", currency: "",
});
const fromLead = (l: PFLead): PFLeadInput => ({
  business_name: l.business_name, contact_name: l.contact_name, email: l.email, linkedin_url: l.linkedin_url, website: l.website, problem: l.problem,
  notes: l.notes, source: l.source, status: l.status, next_follow_up: l.next_follow_up, country: l.country, timezone: l.timezone, currency: l.currency,
});

export function LeadDialog({ lead, open, onClose, initial }: { lead?: PFLead | null; open: boolean; onClose: () => void; initial?: Partial<PFLeadInput> }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [f, setF] = useState<PFLeadInput>(() => ({ ...(lead ? fromLead(lead) : blank()), ...initial }));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = <K extends keyof PFLeadInput>(k: K, v: PFLeadInput[K]) => setF((x) => ({ ...x, [k]: v }));

  const save = useMutation({
    mutationFn: () => (lead ? api.pfUpdateLead(lead.id, f) : api.pfCreateLead(f)),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["pf"] }); toast(lead ? "Lead updated" : "Lead added"); onClose(); },
    onError: (e) => { setErrors(fieldErrors(e)); toast(Object.keys(fieldErrors(e)).length ? "Please fix the highlighted fields" : errMsg(e), "error"); },
  });
  const remove = useMutation({
    mutationFn: () => api.pfDeleteLead(lead!.id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["pf"] }); toast("Lead deleted"); onClose(); },
    onError: (e) => toast(errMsg(e), "error"),
  });
  const txt = (k: keyof PFLeadInput, label: string, extra: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <Input label={label} value={(f[k] as string) ?? ""} error={errors[k]} onChange={(e) => set(k, e.target.value as never)} {...extra} />
  );

  return (
    <Dialog open={open} onClose={onClose} title={lead ? `Edit ${lead.business_name}` : "Add lead"}>
      <form onSubmit={(e) => { e.preventDefault(); setErrors({}); save.mutate(); }} className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">{txt("business_name", "Business name", { required: true, maxLength: 200 })}</div>
        {txt("contact_name", "Contact name")}
        {txt("email", "Email", { type: "email", autoComplete: "off" })}
        {txt("linkedin_url", "LinkedIn URL", { placeholder: "https://linkedin.com/in/…" })}
        {txt("website", "Website", { placeholder: "acme.com" })}
        <div className="space-y-1.5 sm:col-span-2">
          <label htmlFor="pf-problem" className="text-sm font-medium">Problem I noticed</label>
          <textarea id="pf-problem" rows={3} maxLength={5000} value={f.problem ?? ""} onChange={(e) => set("problem", e.target.value)} className="w-full rounded-xl border border-border bg-card p-3 text-sm" placeholder="e.g. Booking form errors on mobile Safari" />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="pf-source" className="text-sm font-medium">Source</label>
          <input id="pf-source" list="pf-sources" value={f.source ?? ""} onChange={(e) => set("source", e.target.value)} className="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm" />
          <datalist id="pf-sources">{LEAD_SOURCES.map((s) => <option key={s} value={s} />)}</datalist>
        </div>
        <div className="space-y-1.5">
          <label htmlFor="pf-status" className="text-sm font-medium">Status</label>
          <select id="pf-status" value={f.status} onChange={(e) => set("status", e.target.value as LeadStatus)} className="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm">
            {LEAD_STATUSES.map((s) => <option key={s} value={s}>{LEAD_STATUS_LABEL[s]}</option>)}
          </select>
        </div>
        <Input label="Next follow-up" type="date" value={f.next_follow_up ?? ""} error={errors.next_follow_up} onChange={(e) => set("next_follow_up", e.target.value || null)} />
        <fieldset className="grid gap-3 rounded-xl border border-border p-3 sm:col-span-2 sm:grid-cols-3">
          <legend className="px-1 text-xs font-medium text-muted">Foreign client (optional)</legend>
          <Input label="Country" value={f.country ?? ""} onChange={(e) => set("country", e.target.value)} onBlur={async () => {
            if (!f.country?.trim() || f.timezone) return;
            try { const r = await api.pfTzSuggest(f.country); if (r.timezone) set("timezone", r.timezone); } catch { /* suggestion is optional */ }
          }} />
          <div className="space-y-1.5">
            <label htmlFor="pf-tz" className="text-sm font-medium">Time zone</label>
            <input id="pf-tz" list="pf-tzs" value={f.timezone ?? ""} onChange={(e) => set("timezone", e.target.value)} placeholder="America/New_York" aria-invalid={!!errors.timezone} className="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm" />
            <datalist id="pf-tzs">{COMMON_TIMEZONES.map((z) => <option key={z} value={z} />)}</datalist>
            {errors.timezone && <p role="alert" className="text-xs text-danger">{errors.timezone}</p>}
          </div>
          {txt("currency", "Currency", { placeholder: "USD", maxLength: 3 })}
          <OverlapPanel timezone={f.timezone ?? ""} />
        </fieldset>
        {lead && <InvoicesPanel leadId={lead.id} defaultCurrency={f.currency || lead.currency} />}
        <div className="space-y-1.5 sm:col-span-2">
          <label htmlFor="pf-notes" className="text-sm font-medium">Notes</label>
          <textarea id="pf-notes" rows={3} maxLength={5000} value={f.notes ?? ""} onChange={(e) => set("notes", e.target.value)} className="w-full rounded-xl border border-border bg-card p-3 text-sm" />
        </div>
        <div className="flex flex-wrap justify-between gap-2 sm:col-span-2">
          {lead ? <Button type="button" variant="danger" disabled={remove.isPending} onClick={() => { if (window.confirm(`Delete ${lead.business_name}?`)) remove.mutate(); }}>Delete</Button> : <span />}
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={!f.business_name.trim() || save.isPending}>{save.isPending ? "Saving…" : "Save"}</Button>
          </div>
        </div>
      </form>
    </Dialog>
  );
}
