"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@fm/shared";
import dynamic from "next/dynamic";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, EmptyState } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { download } from "@/lib/download";
import { cn } from "@/lib/utils";

const NetFeeBars = dynamic(() => import("@/components/charts").then((m) => m.NetFeeBars), { ssr: false, loading: () => <div className="h-64" /> });

const TABS = ["overview", "invoices", "expenses", "payments", "fees"] as const;
type Tab = (typeof TABS)[number];
const money = (n: number, c = "USD") => new Intl.NumberFormat(undefined, { style: "currency", currency: c }).format(n);

export default function Finance() {
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("overview");
  const [group, setGroup] = useState<"month" | "platform" | "client">("month");
  const [inv, setInv] = useState({ description: "", quantity: "1", unit_price: "", tax: "0" });
  const [exp, setExp] = useState({ amount: "", category: "software", description: "" });
  const [pay, setPay] = useState({ platform: "direct", gross: "", note: "" });
  const [fee, setFee] = useState({ platform: "fiverr", amount: "100" });
  const summary = useQuery({ queryKey: ["fin-summary"], queryFn: api.financeSummary });
  const report = useQuery({ queryKey: ["fin-report", group], queryFn: () => api.report(group) });
  const invoices = useQuery({ queryKey: ["invoices"], queryFn: api.invoices, enabled: tab === "invoices" });
  const expenses = useQuery({ queryKey: ["expenses"], queryFn: api.expenses, enabled: tab === "expenses" });
  const payments = useQuery({ queryKey: ["payments"], queryFn: api.payments, enabled: tab === "payments" });
  const feeRes = useQuery({ queryKey: ["fee", fee], queryFn: () => api.feeCalc(fee.platform, Number(fee.amount) || 0), enabled: tab === "fees" });
  const refresh = () => ["fin-summary", "fin-report", "invoices", "expenses", "payments"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const onErr = (e: unknown) => toast(e instanceof ApiError ? e.message : "Something went wrong", "error");
  const addInv = useMutation({ mutationFn: () => api.createInvoice({ items: [{ description: inv.description, quantity: Number(inv.quantity) || 1, unit_price: Number(inv.unit_price) || 0 }], tax_pct: Number(inv.tax) || 0 }), onSuccess: () => { setInv({ ...inv, description: "", unit_price: "" }); refresh(); toast("Draft invoice created"); }, onError: onErr });
  const act = useMutation({ mutationFn: ({ id, a }: { id: string; a: "send" | "pay" | "void" }) => api.invoiceAction(id, a), onSuccess: refresh, onError: onErr });
  const addExp = useMutation({ mutationFn: () => api.addExpense({ amount: Number(exp.amount), category: exp.category, description: exp.description }), onSuccess: () => { setExp({ ...exp, amount: "", description: "" }); refresh(); }, onError: onErr });
  const addPay = useMutation({ mutationFn: () => api.addPayment({ platform: pay.platform, gross: Number(pay.gross), note: pay.note }), onSuccess: () => { setPay({ ...pay, gross: "", note: "" }); refresh(); }, onError: onErr });
  const s = summary.data;
  const cur = s?.currency ?? "USD";

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <h1 className="text-2xl font-bold">Finance</h1>
      <div role="tablist" className="flex flex-wrap gap-2">{TABS.map((t) => <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={cn("rounded-xl px-3 py-1.5 text-sm capitalize", tab === t ? "bg-brand/10 text-brand" : "text-muted")}>{t}</button>)}</div>

      {tab === "overview" && (<>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[["Net this month", s && money(s.month.net, cur)], ["Outstanding invoices", s && money(s.outstanding_invoices, cur)], ["Overdue invoices", s?.overdue_invoices], ["Set aside for tax", s && money(s.tax_set_aside, cur)]].map(([l, v]) => <Card key={String(l)}><p className="text-sm text-muted">{l}</p><p className="mt-1 text-2xl font-bold">{v ?? "-"}</p></Card>)}
        </div>
        {s?.goal_progress != null && <Card><p className="text-sm">Monthly goal: {Math.round(s.goal_progress * 100)}% of {money(s.monthly_income_goal, cur)}</p><div className="mt-2 h-2 rounded-full bg-border"><div className="h-2 rounded-full bg-brand" style={{ width: `${Math.min(100, s.goal_progress * 100)}%` }} /></div></Card>}
        <Card className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">Earnings</h2>
            <div className="flex gap-2"><select aria-label="Group by" value={group} onChange={(e) => setGroup(e.target.value as typeof group)} className="h-8 rounded-xl border border-border bg-card px-2 text-sm"><option value="month">by month</option><option value="platform">by platform</option><option value="client">by client</option></select>
              <Button size="sm" variant="outline" onClick={() => download(`/finance/report.csv?group_by=${group}`, "earnings.csv")}>Export CSV</Button></div></div>
          {report.data?.rows.length === 0 ? <EmptyState title="No payments yet" hint="Record a payment or complete an order to see earnings here." /> : (
            <NetFeeBars data={report.data?.rows ?? []} />)}
          {report.data && <p className="text-sm text-muted">Gross {money(report.data.totals.gross, cur)} · fees {money(report.data.totals.fees, cur)} · expenses {money(report.data.totals.expenses, cur)} · <strong>profit {money(report.data.totals.profit, cur)}</strong></p>}
          {!!report.data?.missing_fx_rates.length && <p role="alert" className="text-xs text-danger">No exchange rate for {report.data.missing_fx_rates.join(", ")} - those amounts are counted 1:1. Set rates in settings.fx.</p>}
          {report.data && <p className="text-xs text-muted">Tax estimate ({report.data.tax.rate_pct}%): {money(report.data.tax.estimated_tax, cur)}. {report.data.tax.disclaimer}</p>}
        </Card>
      </>)}

      {tab === "invoices" && (<>
        <Card><form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (inv.description) addInv.mutate(); }}>
          <Input label="Description" value={inv.description} onChange={(e) => setInv({ ...inv, description: e.target.value })} /><Input label="Qty" type="number" value={inv.quantity} onChange={(e) => setInv({ ...inv, quantity: e.target.value })} />
          <Input label="Unit price" type="number" value={inv.unit_price} onChange={(e) => setInv({ ...inv, unit_price: e.target.value })} /><Input label="Tax %" type="number" value={inv.tax} onChange={(e) => setInv({ ...inv, tax: e.target.value })} /><Button type="submit" disabled={!inv.description}>Create draft</Button></form></Card>
        <Card className="overflow-x-auto p-0"><table className="w-full text-sm"><thead className="text-left text-xs text-muted"><tr><th className="p-3">Number</th><th>Client</th><th>Total</th><th>Status</th><th /></tr></thead><tbody>
          {invoices.data?.map((i) => (<tr key={i.id} className="border-t border-border"><td className="p-3 font-medium">{i.number}</td><td>{i.client_name || "-"}</td><td>{money(i.total, i.currency)}</td><td className={i.overdue ? "text-danger" : ""}>{i.overdue ? "overdue" : i.status}</td>
            <td className="space-x-1 p-2 text-right"><Button size="sm" variant="outline" onClick={() => download(`/finance/invoices/${i.id}/pdf`, `${i.number}.pdf`)}>PDF</Button>
              {i.status === "draft" && <Button size="sm" variant="outline" onClick={() => act.mutate({ id: i.id, a: "send" })}>Mark sent</Button>}
              {(i.status === "sent" || i.status === "draft") && <Button size="sm" onClick={() => act.mutate({ id: i.id, a: "pay" })}>Mark paid</Button>}
              {i.status !== "paid" && i.status !== "void" && <Button size="sm" variant="ghost" onClick={() => act.mutate({ id: i.id, a: "void" })}>Void</Button>}</td></tr>))}
        </tbody></table></Card></>)}

      {tab === "expenses" && (<>
        <Card><form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (exp.amount) addExp.mutate(); }}>
          <Input label="Amount" type="number" value={exp.amount} onChange={(e) => setExp({ ...exp, amount: e.target.value })} /><Input label="Category" value={exp.category} onChange={(e) => setExp({ ...exp, category: e.target.value })} /><Input label="Description" value={exp.description} onChange={(e) => setExp({ ...exp, description: e.target.value })} /><Button type="submit" disabled={!exp.amount}>Add expense</Button></form></Card>
        <Card className="divide-y divide-border p-0">{expenses.data?.map((e) => <div key={e.id} className="flex justify-between px-4 py-2 text-sm"><span>{e.spent_on} · {e.category} {e.description && `- ${e.description}`}</span><span>{money(e.amount, e.currency)}</span></div>)}</Card></>)}

      {tab === "payments" && (<>
        <Card><form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (pay.gross) addPay.mutate(); }}>
          <Input label="Platform" value={pay.platform} onChange={(e) => setPay({ ...pay, platform: e.target.value })} /><Input label="Gross amount" type="number" value={pay.gross} onChange={(e) => setPay({ ...pay, gross: e.target.value })} /><Input label="Note" value={pay.note} onChange={(e) => setPay({ ...pay, note: e.target.value })} /><Button type="submit" disabled={!pay.gross}>Record payment</Button></form>
          <p className="mt-2 text-xs text-muted">Platform fees are applied automatically from the fee schedule (see Fees tab).</p></Card>
        <Card className="divide-y divide-border p-0">{payments.data?.map((p) => <div key={p.id} className="flex justify-between px-4 py-2 text-sm"><span>{p.received_on} · {p.platform} · {p.source} {p.note && `- ${p.note}`}</span><span>{money(p.net, p.currency)} <span className="text-xs text-muted">(gross {p.gross}, fee {p.fee})</span></span></div>)}</Card></>)}

      {tab === "fees" && (
        <Card className="space-y-3"><h2 className="font-semibold">Platform fee calculator</h2>
          <div className="flex flex-wrap items-end gap-3"><div className="space-y-1.5"><label htmlFor="fp" className="text-sm font-medium">Platform</label><select id="fp" value={fee.platform} onChange={(e) => setFee({ ...fee, platform: e.target.value })} className="h-10 rounded-xl border border-border bg-card px-3 text-sm">{["fiverr", "upwork", "freelancer", "peopleperhour", "toptal", "guru", "linkedin", "contra", "direct"].map((p) => <option key={p}>{p}</option>)}</select></div>
            <Input label="Gross amount" type="number" value={fee.amount} onChange={(e) => setFee({ ...fee, amount: e.target.value })} /></div>
          {feeRes.data && <p className="text-lg">Fee <strong>{feeRes.data.fee}</strong> → you keep <strong>{feeRes.data.net}</strong></p>}
          <p className="text-xs text-muted">Default fee schedule - platforms change fees; override per platform in your settings.</p></Card>)}
    </div>
  );
}
