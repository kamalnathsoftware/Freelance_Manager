"use client";
import { useQuery } from "@tanstack/react-query";
import { LEAD_STATUSES, LEAD_STATUS_LABEL } from "@fm/shared";
import { Flame, Trophy } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Card, EmptyState, Skeleton } from "@/components/ui/card";
import { Disclaimer } from "@/components/project-finder/invoices-panel";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const pct = (r: number | null) => (r == null ? "-" : `${Math.round(r * 1000) / 10}%`);
const money = (m: Record<string, number>) => {
  const e = Object.entries(m);
  return e.length ? e.map(([c, v]) => `${c} ${v.toLocaleString()}`).join(" + ") : "-";
};
const PERIODS = [{ label: "All time", days: undefined }, { label: "Last 30 days", days: 30 }, { label: "Last 90 days", days: 90 }, { label: "Last year", days: 365 }];

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card className="space-y-1">
      <p className="text-sm text-muted">{label}</p>
      <p className="text-2xl font-bold">{value}</p>
      {sub && <p className="text-xs text-muted">{sub}</p>}
    </Card>
  );
}

function Bar({ value, max, className }: { value: number; max: number; className?: string }) {
  return <div className="h-2 flex-1 rounded-full bg-border/60" aria-hidden><div className={cn("h-full rounded-full bg-brand", className)} style={{ width: `${max ? (value / max) * 100 : 0}%` }} /></div>;
}

export default function StatsPage() {
  const [days, setDays] = useState<number | undefined>(undefined);
  const stats = useQuery({ queryKey: ["pf", "stats", days], queryFn: () => api.pfStats(days) });
  const firc = useQuery({ queryKey: ["pf", "invoices", "pending"], queryFn: () => api.pfInvoices({ firc: "pending" }) });

  if (stats.isLoading) return <Skeleton className="h-64" />;
  if (stats.isError || !stats.data) return <Card role="alert" className="text-sm text-danger">Could not load stats. <button className="underline" onClick={() => stats.refetch()}>Retry</button></Card>;
  const s = stats.data, p = s.proposals;
  const maxFunnel = Math.max(1, ...LEAD_STATUSES.map((k) => s.leads.by_status[k] ?? 0));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">Reply rate = proposals that got a reply ÷ proposals sent. Win rate = won ÷ sent.</p>
        <div className="flex gap-1" role="group" aria-label="Period">
          {PERIODS.map((x) => <button key={x.label} aria-pressed={days === x.days} onClick={() => setDays(x.days)} className={cn("rounded-xl border px-3 py-1.5 text-sm", days === x.days ? "border-brand bg-brand/10 text-brand" : "border-border text-muted hover:border-brand")}>{x.label}</button>)}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="Proposals sent" value={String(p.sent)} sub={`${p.pending} still waiting`} />
        <Kpi label="Reply rate" value={pct(p.reply_rate)} sub={`${p.replied} repl${p.replied === 1 ? "y" : "ies"}`} />
        <Kpi label="Win rate" value={pct(p.win_rate)} sub={`${p.won} won · ${p.lost} lost`} />
        <Kpi label="Earnings (won)" value={money(p.earnings)} sub="per currency, no conversion" />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card className="space-y-2">
          <h2 className="flex items-center gap-2 font-semibold"><Trophy size={16} aria-hidden /> Best-performing source</h2>
          {s.best_source ? (
            <>
              <p className="text-xl font-bold">{s.best_source.source}</p>
              <p className="text-sm text-muted">{s.best_source.reason}</p>
              <p className="text-xs text-muted">Rule: {s.best_source.rule}.</p>
            </>
          ) : <p className="text-sm text-muted">Nothing to rank yet - once a proposal gets a reply or a win, the best source appears here.</p>}
        </Card>
        <Card className="space-y-2">
          <h2 className="flex items-center gap-2 font-semibold"><Flame size={16} aria-hidden /> Outreach</h2>
          <p className="text-sm">Today <b>{s.outreach.today}</b> / {s.outreach.goal} · last 7 days <b>{s.outreach.last_7_days}</b> · last 30 days <b>{s.outreach.last_30_days}</b></p>
          <p className="text-sm text-muted">Streak {s.outreach.streak} day{s.outreach.streak === 1 ? "" : "s"} (best {s.outreach.best_streak}). <Link href="/project-finder/leads" className="underline">Log messages on Leads</Link>.</p>
        </Card>
      </div>

      <Card className="space-y-2">
        <h2 className="font-semibold">By source</h2>
        {s.by_source.length === 0 ? <EmptyState title="No proposals yet" hint="Log proposals on the Proposals tab to compare your sources." /> : (
          <div className="-mx-2 overflow-x-auto px-2">
            <table className="w-full min-w-[34rem] text-sm">
              <caption className="sr-only">Proposal results by source</caption>
              <thead><tr className="text-left text-xs text-muted"><th className="py-1 pr-3 font-medium">Source</th><th className="pr-3 font-medium">Sent</th><th className="pr-3 font-medium">Replied</th><th className="pr-3 font-medium">Won</th><th className="pr-3 font-medium">Reply rate</th><th className="pr-3 font-medium">Win rate</th><th className="font-medium">Earnings</th></tr></thead>
              <tbody>
                {s.by_source.map((r) => (
                  <tr key={r.source} className="border-t border-border">
                    <th scope="row" className="py-2 pr-3 text-left font-medium">{r.source}{s.best_source?.source === r.source && <span className="ml-1 text-xs text-brand">★</span>}</th>
                    <td className="pr-3">{r.sent}</td><td className="pr-3">{r.replied}</td><td className="pr-3">{r.won}</td><td className="pr-3">{pct(r.reply_rate)}</td><td className="pr-3">{pct(r.win_rate)}</td><td>{money(r.earnings)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-xs text-muted">{s.earnings_basis}.</p>
      </Card>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card className="space-y-2">
          <h2 className="font-semibold">Lead funnel <span className="text-sm font-normal text-muted">({s.leads.total} leads{s.leads.follow_ups_due ? `, ${s.leads.follow_ups_due} follow-up${s.leads.follow_ups_due > 1 ? "s" : ""} due` : ""})</span></h2>
          <ul className="space-y-1.5">
            {LEAD_STATUSES.map((k) => (
              <li key={k} className="flex items-center gap-3 text-sm"><span className="w-28 shrink-0 text-muted">{LEAD_STATUS_LABEL[k]}</span><Bar value={s.leads.by_status[k] ?? 0} max={maxFunnel} className={k === "won" ? "bg-success" : k === "lost" ? "bg-danger" : ""} /><span className="w-6 text-right">{s.leads.by_status[k] ?? 0}</span></li>
            ))}
          </ul>
          {s.leads.by_source.length > 0 && (
            <>
              <h3 className="pt-2 text-sm font-medium">Leads by source</h3>
              <ul className="text-sm text-muted">{s.leads.by_source.map((x) => <li key={x.source}>{x.source}: {x.leads} lead{x.leads > 1 ? "s" : ""}, {x.won} won</li>)}</ul>
            </>
          )}
        </Card>
        <Card className="space-y-2">
          <h2 className="font-semibold">Foreign clients</h2>
          <p className="text-sm">{s.foreign.invoices} invoice{s.foreign.invoices === 1 ? "" : "s"} recorded · invoiced {money(s.foreign.invoiced)}</p>
          {s.foreign.countries.length > 0 && <p className="text-sm text-muted">Countries: {s.foreign.countries.join(", ")}</p>}
          <p className="text-sm"><b>{s.foreign.firc_pending}</b> awaiting FIRC / e-FIRA</p>
          {!!firc.data?.length && <ul className="text-sm text-muted">{firc.data.map((i) => <li key={i.id}><Link className="underline" href={`/project-finder/leads?lead=${i.lead_id}`}>{i.lead_name || "Lead"}</Link> - {i.currency} {i.amount.toLocaleString()} via {i.payment_method} ({i.invoice_date})</li>)}</ul>}
          <Disclaimer />
        </Card>
      </div>
    </div>
  );
}
