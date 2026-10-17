"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PAYMENT_METHODS, type PFInvoiceInput, type PaymentMethod } from "@fm/shared";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { errMsg, fieldErrors } from "@/lib/pf";

export function Disclaimer() {
  const info = useQuery({ queryKey: ["pf", "foreign-info"], queryFn: api.pfForeignInfo, staleTime: Infinity });
  return <p className="rounded-xl bg-border/30 p-2 text-xs text-muted" role="note">{info.data?.disclaimer ?? "This is a record-keeping aid, not tax advice. Confirm GST/LUT and FIRC/e-FIRA rules with a chartered accountant."}</p>;
}

/** Payment records for one lead (won project): amount, method, FIRC/e-FIRA received, LUT note. */
export function InvoicesPanel({ leadId, defaultCurrency }: { leadId: string; defaultCurrency: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const invoices = useQuery({ queryKey: ["pf", "invoices", leadId], queryFn: () => api.pfInvoices({ lead_id: leadId }) });
  const [adding, setAdding] = useState(false);
  const blank = (): PFInvoiceInput => ({ lead_id: leadId, amount: 0, currency: defaultCurrency || "USD", payment_method: "wise", reference: "", lut_note: "", firc_received: false });
  const [f, setF] = useState<PFInvoiceInput>(blank);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const reload = () => { qc.invalidateQueries({ queryKey: ["pf", "invoices"] }); qc.invalidateQueries({ queryKey: ["pf", "stats"] }); };
  const onErr = (e: unknown) => toast(errMsg(e), "error");
  const add = useMutation({
    mutationFn: () => api.pfCreateInvoice({ ...f, invoice_date: f.invoice_date || undefined }),
    onSuccess: () => { reload(); setAdding(false); setF(blank()); toast("Invoice recorded"); },
    onError: (e) => { setErrors(fieldErrors(e)); onErr(e); },
  });
  const toggle = useMutation({ mutationFn: ({ id, firc }: { id: string; firc: boolean }) => api.pfUpdateInvoice(id, { firc_received: firc }), onSuccess: reload, onError: onErr });
  const del = useMutation({ mutationFn: api.pfDeleteInvoice, onSuccess: reload, onError: onErr });

  return (
    <fieldset className="space-y-2 rounded-xl border border-border p-3 sm:col-span-2">
      <legend className="px-1 text-xs font-medium text-muted">Invoices & payments</legend>
      <Disclaimer />
      {invoices.isError && <p role="alert" className="text-xs text-danger">Could not load invoices.</p>}
      {invoices.data?.length === 0 && !adding && <p className="text-xs text-muted">No invoices yet. Record one when a project is won and paid.</p>}
      <ul className="space-y-1.5">
        {invoices.data?.map((i) => (
          <li key={i.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-border px-3 py-2 text-sm">
            <span className="font-medium">{i.currency} {i.amount.toLocaleString()}</span>
            <span className="text-xs text-muted">{i.invoice_date} · {i.payment_method}{i.reference && ` · ${i.reference}`}</span>
            <label className="ml-auto flex items-center gap-1.5 text-xs"><input type="checkbox" checked={i.firc_received} disabled={toggle.isPending} onChange={(e) => toggle.mutate({ id: i.id, firc: e.target.checked })} /> FIRC / e-FIRA received</label>
            <button type="button" aria-label={`Delete invoice ${i.reference || i.invoice_date}`} className="rounded-lg p-1 text-muted hover:text-danger" onClick={() => { if (window.confirm("Delete this invoice record?")) del.mutate(i.id); }}><Trash2 size={14} /></button>
            {i.lut_note && <p className="w-full text-xs text-muted">LUT: {i.lut_note}</p>}
          </li>
        ))}
      </ul>
      {adding ? (
        <div className="grid gap-3 sm:grid-cols-3">
          <Input label="Amount" type="number" min={0} step="0.01" value={f.amount || ""} error={errors.amount} onChange={(e) => setF({ ...f, amount: Number(e.target.value) })} />
          <Input label="Currency" value={f.currency ?? ""} maxLength={3} error={errors.currency} onChange={(e) => setF({ ...f, currency: e.target.value })} />
          <Input label="Invoice date" type="date" value={f.invoice_date ?? ""} onChange={(e) => setF({ ...f, invoice_date: e.target.value })} />
          <div className="space-y-1.5">
            <label htmlFor="inv-m" className="text-sm font-medium">Paid via</label>
            <select id="inv-m" value={f.payment_method} onChange={(e) => setF({ ...f, payment_method: e.target.value as PaymentMethod })} className="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm capitalize">
              {PAYMENT_METHODS.map((m) => <option key={m} value={m}>{m === "swift" ? "SWIFT" : m[0].toUpperCase() + m.slice(1)}</option>)}
            </select>
          </div>
          <Input label="Reference" value={f.reference ?? ""} maxLength={80} onChange={(e) => setF({ ...f, reference: e.target.value })} />
          <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" checked={!!f.firc_received} onChange={(e) => setF({ ...f, firc_received: e.target.checked })} /> FIRC / e-FIRA received</label>
          <div className="space-y-1.5 sm:col-span-3">
            <label htmlFor="inv-lut" className="text-sm font-medium">LUT note</label>
            <textarea id="inv-lut" rows={2} maxLength={2000} value={f.lut_note ?? ""} onChange={(e) => setF({ ...f, lut_note: e.target.value })} placeholder="e.g. Export under LUT, ARN …, valid FY 2026-27" className="w-full rounded-xl border border-border bg-card p-2 text-sm" />
          </div>
          <div className="flex gap-2 sm:col-span-3">
            <Button type="button" disabled={!f.amount || f.amount <= 0 || add.isPending} onClick={() => { setErrors({}); add.mutate(); }}>Save invoice</Button>
            <Button type="button" variant="outline" onClick={() => { setAdding(false); setErrors({}); }}>Cancel</Button>
          </div>
        </div>
      ) : (
        <Button type="button" size="sm" variant="outline" onClick={() => setAdding(true)}><Plus size={14} /> Add invoice</Button>
      )}
    </fieldset>
  );
}
