"use client";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import dynamic from "next/dynamic";
import Link from "next/link";
import { PlatformBadge } from "@/components/platform-badge";
import { Card, EmptyState, Skeleton } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";

const EarningsChart = dynamic(() => import("@/components/charts").then((m) => m.EarningsChart), { ssr: false, loading: () => <Skeleton className="h-64" /> });
const FunnelChart = dynamic(() => import("@/components/charts").then((m) => m.FunnelChart), { ssr: false, loading: () => <Skeleton className="h-64" /> });
const Sparkline = dynamic(() => import("@/components/charts").then((m) => m.Sparkline), { ssr: false });

const money = (n: number, c: string) => new Intl.NumberFormat(undefined, { style: "currency", currency: c, maximumFractionDigits: 0 }).format(n);

export default function Dashboard() {
  const { t } = useT();
  const ov = useQuery({ queryKey: ["analytics", 30], queryFn: () => api.analytics(30) });
  const brief = useQuery({ queryKey: ["briefing", false], queryFn: () => api.briefing(false) });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts });
  const d = ov.data;
  const k = d?.kpis;
  const cards = [
    { label: t("dash.net"), value: k ? money(k.net_earnings, d!.currency) : "", sub: k?.change_pct != null ? `${k.change_pct >= 0 ? "▲" : "▼"} ${Math.abs(k.change_pct)}% vs previous` : "" },
    { label: t("dash.winrate"), value: k ? `${Math.round(k.win_rate * 100)}%` : "", sub: k ? `${k.proposals_submitted} proposals` : "" },
    { label: t("dash.pipeline"), value: k ? money(k.open_pipeline_value, d!.currency) : "", sub: "" },
    { label: t("dash.orders"), value: k ? String(k.active_orders) : "", sub: k?.avg_response_minutes != null ? `avg reply ${k.avg_response_minutes} min` : "" },
  ];
  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <h1 className="text-2xl font-bold">{t("dash.title")}</h1>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {cards.map((c, i) => (
          <motion.div key={c.label} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
            <Card>
              <p className="text-sm text-muted">{c.label}</p>
              {ov.isLoading ? <Skeleton className="mt-2 h-8 w-24" /> : <p className="mt-1 text-2xl font-bold">{c.value}</p>}
              <p className="text-xs text-muted">{c.sub}</p>
              {i === 0 && d && <Sparkline data={d.earnings_series} />}
            </Card>
          </motion.div>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="mb-3 flex items-center justify-between"><h2 className="font-semibold">Earnings (30 days)</h2><Link href="/analytics" className="text-sm text-brand">Full analytics →</Link></div>
          {d ? <EarningsChart data={d.earnings_series} currency={d.currency} /> : <Skeleton className="h-64" />}
        </Card>
        <Card className="space-y-3">
          <h2 className="font-semibold">{t("dash.today")}</h2>
          <p className="text-sm">{brief.data?.headline ?? <Skeleton className="h-5" />}</p>
          {d?.upcoming_deadlines.length === 0 && !brief.isLoading && <EmptyState title="No deadlines this week" hint="Orders, tasks and invoices with due dates show up here." />}
          <ul className="space-y-1.5 text-sm">
            {d?.upcoming_deadlines.slice(0, 5).map((x) => <li key={x.title + x.at}><Link href={x.href} className="hover:text-brand">{x.title}</Link> <span className="text-xs text-muted">{new Date(x.at).toLocaleDateString()}</span></li>)}
          </ul>
          <div className="flex flex-wrap gap-2">{accounts.data?.map((a) => <PlatformBadge key={a.id} platform={a.platform} />)}</div>
        </Card>
      </div>
      <Card>
        <h2 className="mb-3 font-semibold">Proposal funnel</h2>
        {d ? <FunnelChart data={d.funnel} /> : <Skeleton className="h-64" />}
      </Card>
    </div>
  );
}
