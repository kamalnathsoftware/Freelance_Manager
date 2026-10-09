"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@fm/shared";
import dynamic from "next/dynamic";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, Skeleton } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { download } from "@/lib/download";

const EarningsChart = dynamic(() => import("@/components/charts").then((m) => m.EarningsChart), { ssr: false, loading: () => <Skeleton className="h-64" /> });
const FunnelChart = dynamic(() => import("@/components/charts").then((m) => m.FunnelChart), { ssr: false, loading: () => <Skeleton className="h-64" /> });
const PlatformPie = dynamic(() => import("@/components/charts").then((m) => m.PlatformPie), { ssr: false, loading: () => <Skeleton className="h-64" /> });

const money = (n: number, c: string) => new Intl.NumberFormat(undefined, { style: "currency", currency: c, maximumFractionDigits: 0 }).format(n);
const RANGES = [{ d: 7, g: "day" }, { d: 30, g: "day" }, { d: 90, g: "week" }, { d: 365, g: "month" }] as const;
const STATUS_TEXT = { ahead: "Ahead of pace", on_track: "On track", behind: "Behind pace" } as const;

function WinRateTable({ title, rows }: { title: string; rows: { key: string; submitted: number; won: number; win_rate: number }[] }) {
  return (
    <div><h3 className="mb-1 text-sm font-semibold">{title}</h3>
      {rows.length === 0 ? <p className="text-sm text-muted">No submitted proposals yet.</p> : (
        <table className="w-full text-sm"><thead className="text-left text-xs text-muted"><tr><th scope="col">Group</th><th scope="col">Sent</th><th scope="col">Won</th><th scope="col">Rate</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.key} className="border-t border-border"><td className="py-1">{r.key}</td><td>{r.submitted}</td><td>{r.won}</td><td>{Math.round(r.win_rate * 100)}%</td></tr>)}</tbody></table>)}
    </div>
  );
}

export default function Analytics() {
  const qc = useQueryClient();
  const toast = useToast();
  const [range, setRange] = useState<(typeof RANGES)[number]>(RANGES[1]);
  const [goalForm, setGoalForm] = useState<{ m?: string; y?: string; h?: string }>({});
  const ov = useQuery({ queryKey: ["analytics", range.d, range.g], queryFn: () => api.analytics(range.d, range.g) });
  const goals = useQuery({ queryKey: ["goals"], queryFn: api.goals });
  const saveGoals = useMutation({
    mutationFn: () => api.saveGoals({ monthly_income: Number(goalForm.m ?? goals.data?.goals.monthly_income ?? 0), yearly_income: Number(goalForm.y ?? goals.data?.goals.yearly_income ?? 0), weekly_hours: Number(goalForm.h ?? goals.data?.goals.weekly_hours ?? 40) }),
    onSuccess: (g) => { qc.setQueryData(["goals"], g); toast("Goals saved"); },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Could not save", "error"),
  });
  const d = ov.data;
  const g = goals.data;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold">Analytics</h1>
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label="Date range" className="flex rounded-xl border border-border p-0.5">
            {RANGES.map((r) => <button key={r.d} aria-pressed={range.d === r.d} onClick={() => setRange(r)} className={`rounded-lg px-3 py-1 text-sm ${range.d === r.d ? "bg-brand text-brand-fg" : "text-muted"}`}>{r.d === 365 ? "1y" : `${r.d}d`}</button>)}
          </div>
          <Button size="sm" variant="outline" onClick={() => download(`/analytics/report.pdf?days=${range.d}`, "business-report.pdf")}>Export PDF</Button>
          <Button size="sm" variant="outline" onClick={() => download(`/finance/report.csv?group_by=month`, "earnings.csv")}>Export CSV</Button>
        </div>
      </div>
      {!!d?.missing_fx_rates.length && <p role="alert" className="rounded-xl bg-danger/10 p-3 text-sm text-danger">No exchange rate for {d.missing_fx_rates.join(", ")}: those amounts are counted 1:1.</p>}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[["Net earnings", d && money(d.kpis.net_earnings, d.currency)], ["Win rate", d && `${Math.round(d.kpis.win_rate * 100)}%`], ["Avg first reply", d && (d.kpis.avg_response_minutes != null ? `${d.kpis.avg_response_minutes} min` : "n/a")], ["Utilization", d && (d.utilization.utilization_pct != null ? `${d.utilization.utilization_pct}%` : "n/a")]].map(([l, v]) => (
          <Card key={String(l)}><p className="text-sm text-muted">{l}</p><p className="mt-1 text-2xl font-bold">{v ?? <Skeleton className="h-8 w-20" />}</p></Card>
        ))}
      </div>

      <Card><h2 className="mb-3 font-semibold">Earnings</h2>{d ? <EarningsChart data={d.earnings_series} currency={d.currency} /> : <Skeleton className="h-64" />}</Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card><h2 className="mb-3 font-semibold">By platform</h2>{d ? (d.by_platform.length ? <PlatformPie data={d.by_platform} /> : <p className="text-sm text-muted">No payments in this period.</p>) : <Skeleton className="h-64" />}</Card>
        <Card><h2 className="mb-3 font-semibold">Top clients</h2>
          <ol className="space-y-1.5 text-sm">{d?.top_clients.map((c) => <li key={c.key} className="flex justify-between"><span>{c.key}</span><span className="font-medium">{money(c.net, d.currency)}</span></li>)}</ol>
          {d?.top_clients.length === 0 && <p className="text-sm text-muted">No client revenue yet.</p>}</Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card><h2 className="mb-1 font-semibold">Proposal funnel</h2><p className="mb-2 text-xs text-muted">Approximate: later steps are lower bounds because stage history isn&apos;t stored.</p>{d ? <FunnelChart data={d.funnel} /> : <Skeleton className="h-64" />}</Card>
        <Card className="space-y-4"><h2 className="font-semibold">Win rate</h2>{d && <><WinRateTable title="By platform" rows={d.win_rate_by.platform} /><WinRateTable title="By price band" rows={d.win_rate_by.price_band} /><WinRateTable title="By template" rows={d.win_rate_by.template} /></>}</Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="space-y-2"><h2 className="font-semibold">Response time (SLA)</h2>
          {d?.response_times.length === 0 && <p className="text-sm text-muted">No replies recorded yet.</p>}
          <ul className="text-sm">{d?.response_times.map((r) => <li key={r.platform} className="flex justify-between border-t border-border py-1"><span className="capitalize">{r.platform}</span><span>{r.avg_response_minutes} min avg · {r.replies} replies</span></li>)}</ul></Card>
        <Card className="space-y-2"><h2 className="font-semibold">Utilization</h2>
          {d && <>
            <div className="h-2 rounded-full bg-border" role="progressbar" aria-label="Utilization" aria-valuenow={Math.min(100, d.utilization.utilization_pct ?? 0)} aria-valuemin={0} aria-valuemax={100}><div className="h-2 rounded-full bg-brand" style={{ width: `${Math.min(100, d.utilization.utilization_pct ?? 0)}%` }} /></div>
            <p className="text-sm text-muted">{d.utilization.tracked_hours}h tracked of {d.utilization.capacity_hours}h capacity · {d.utilization.billable_pct ?? 0}% billable</p></>}</Card>
      </div>

      <Card className="space-y-4">
        <h2 className="font-semibold">Income goals &amp; forecast</h2>
        {g && (<>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-1"><p className="text-sm">This month: <strong>{money(g.month.earned, g.currency)}</strong>{g.month.goal ? ` of ${money(g.month.goal, g.currency)}` : ""} {g.month.status && <span className="ml-1 rounded-full bg-brand/10 px-2 py-0.5 text-xs text-brand">{STATUS_TEXT[g.month.status]}</span>}</p>
              {g.month.pct != null && <div className="relative h-3 rounded-full bg-border" role="progressbar" aria-label="Monthly goal" aria-valuenow={Math.min(100, g.month.pct)} aria-valuemin={0} aria-valuemax={100}><div className="h-3 rounded-full bg-brand" style={{ width: `${Math.min(100, g.month.pct)}%` }} /><div className="absolute top-0 h-3 w-0.5 bg-fg" style={{ left: `${g.month.expected_pct_by_today}%` }} title="Where you'd be at an even pace" /></div>}
              <p className="text-xs text-muted">Marker = even-pace position for today ({g.month.expected_pct_by_today}%).</p></div>
            <div className="space-y-1"><p className="text-sm">This year: <strong>{money(g.year.earned, g.currency)}</strong>{g.year.goal ? ` of ${money(g.year.goal, g.currency)} (${g.year.pct}%)` : ""}</p></div>
          </div>
          <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
            {[["Run-rate month end", g.forecast.run_rate_month_end], ["+ committed orders", g.forecast.month_end_with_committed], ["+ weighted pipeline", g.forecast.month_end_with_pipeline], ["Weighted pipeline", g.forecast.pipeline_weighted]].map(([l, v]) => <div key={String(l)} className="rounded-xl border border-border p-3"><dt className="text-xs text-muted">{l}</dt><dd className="text-lg font-semibold">{money(Number(v), g.currency)}</dd></div>)}
          </dl>
          <p className="text-xs text-muted">{g.forecast.assumptions.note} Stage win probability from {String(g.forecast.assumptions.source)}.</p>
        </>)}
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); saveGoals.mutate(); }}>
          <Input label="Monthly income goal" type="number" value={goalForm.m ?? g?.goals.monthly_income ?? ""} onChange={(e) => setGoalForm({ ...goalForm, m: e.target.value })} />
          <Input label="Yearly income goal" type="number" value={goalForm.y ?? g?.goals.yearly_income ?? ""} onChange={(e) => setGoalForm({ ...goalForm, y: e.target.value })} />
          <Input label="Weekly hours" type="number" value={goalForm.h ?? g?.goals.weekly_hours ?? ""} onChange={(e) => setGoalForm({ ...goalForm, h: e.target.value })} />
          <Button type="submit" disabled={saveGoals.isPending}>Save goals</Button>
        </form>
      </Card>
    </div>
  );
}
