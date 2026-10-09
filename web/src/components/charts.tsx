"use client";
// All recharts usage lives here so pages can lazy-load it (next/dynamic) and keep first-load JS small.
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const BRAND = "hsl(var(--brand))";
const MUTED = "hsl(var(--muted))";
// Distinct, colour-blind-friendly series colours that keep contrast on light and dark cards.
const TIP = {
  contentStyle: { background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 12, color: "hsl(var(--fg))" },
  labelStyle: { color: "hsl(var(--fg))" },
  itemStyle: { color: "hsl(var(--fg))" },
} as const;
export const SERIES = ["#4f46e5", "#0ea5e9", "#16a34a", "#d97706", "#db2777", "#7c3aed"];

export function EarningsChart({ data, currency }: { data: { key: string; net: number }[]; currency: string }) {
  return (
    <div className="h-64" role="img" aria-label={`Net earnings over time in ${currency}`}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
          <XAxis dataKey="key" stroke={MUTED} fontSize={11} tickFormatter={(v: string) => v.slice(-5)} minTickGap={24} />
          <YAxis stroke={MUTED} fontSize={11} width={48} />
          <Tooltip {...TIP} formatter={(v: number) => [`${currency} ${v.toLocaleString()}`, "Net"]} />
          <Area dataKey="net" stroke={BRAND} fill="hsl(var(--brand) / 0.18)" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Sparkline({ data }: { data: { net: number }[] }) {
  return (
    <div className="h-8" aria-hidden>
      <ResponsiveContainer width="100%" height="100%"><AreaChart data={data}><Area dataKey="net" stroke={BRAND} fill="hsl(var(--brand) / 0.15)" strokeWidth={2} /></AreaChart></ResponsiveContainer>
    </div>
  );
}

export function FunnelChart({ data }: { data: { stage: string; count: number }[] }) {
  return (
    <div className="h-64" role="img" aria-label="Proposal funnel by stage">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 8 }}>
          <XAxis type="number" hide />
          <YAxis type="category" dataKey="stage" stroke={MUTED} fontSize={12} width={84} />
          <Tooltip {...TIP} />
          <Bar dataKey="count" fill={BRAND} radius={[0, 8, 8, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function PlatformPie({ data }: { data: { key: string; net: number }[] }) {
  const rows = data.filter((d) => d.net > 0);
  return (
    <div className="h-64" role="img" aria-label="Net earnings share by platform">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={rows} dataKey="net" nameKey="key" innerRadius={48} outerRadius={80} paddingAngle={2}>
            {rows.map((_, i) => <Cell key={i} fill={SERIES[i % SERIES.length]} />)}
          </Pie>
          <Legend />
          <Tooltip {...TIP} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

export function NetFeeBars({ data }: { data: { key: string; net: number; fee: number }[] }) {
  return (
    <div className="h-64" role="img" aria-label="Net earnings and platform fees">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <XAxis dataKey="key" stroke={MUTED} fontSize={12} /><YAxis stroke={MUTED} fontSize={12} />
          <Tooltip {...TIP} />
          <Legend />
          <Bar dataKey="net" name="Net" fill={BRAND} radius={[6, 6, 0, 0]} />
          <Bar dataKey="fee" name="Fees" fill="hsl(var(--muted))" radius={[6, 6, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
