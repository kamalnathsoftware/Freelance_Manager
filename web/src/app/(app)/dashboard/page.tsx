"use client";
import { Area, AreaChart, Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { motion } from "framer-motion";
import { PlatformBadge } from "@/components/platform-badge";
import { Card, EmptyState } from "@/components/ui/card";

// Placeholder series until the analytics module (phase 8) feeds real data.
const earnings = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d, i) => ({ d, v: [120, 340, 90, 520, 410, 0, 260][i] }));
const funnel = [
  { stage: "Found", n: 48 }, { stage: "Proposal", n: 21 }, { stage: "Submitted", n: 14 },
  { stage: "Interview", n: 6 }, { stage: "Won", n: 3 },
];
const kpis = [
  { label: "Earnings (7d)", value: "$1,740" }, { label: "Unread messages", value: "0" },
  { label: "Active orders", value: "0" }, { label: "Pending bids", value: "0" },
];

export default function Dashboard() {
  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {kpis.map((k, i) => (
          <motion.div key={k.label} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
            <Card>
              <p className="text-sm text-muted">{k.label}</p>
              <p className="mt-1 text-2xl font-bold">{k.value}</p>
              <div className="mt-2 h-8" aria-hidden>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={earnings}><Area dataKey="v" stroke="hsl(var(--brand))" fill="hsl(var(--brand) / 0.15)" strokeWidth={2} /></AreaChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </motion.div>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <h2 className="mb-3 font-semibold">Earnings</h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={earnings}>
                <XAxis dataKey="d" stroke="hsl(var(--muted))" fontSize={12} /><YAxis stroke="hsl(var(--muted))" fontSize={12} />
                <Tooltip /><Area dataKey="v" stroke="hsl(var(--brand))" fill="hsl(var(--brand) / 0.2)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card>
          <h2 className="mb-3 font-semibold">Today</h2>
          <EmptyState title="Nothing yet" hint="Connect a platform to see messages, deadlines and matching jobs here." />
          <div className="mt-3 flex flex-wrap gap-2">{["upwork", "fiverr", "freelancer"].map((p) => <PlatformBadge key={p} platform={p} />)}</div>
        </Card>
      </div>
      <Card>
        <h2 className="mb-3 font-semibold">Pipeline funnel</h2>
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={funnel} layout="vertical">
              <XAxis type="number" hide /><YAxis type="category" dataKey="stage" stroke="hsl(var(--muted))" fontSize={12} width={80} />
              <Tooltip /><Bar dataKey="n" fill="hsl(var(--brand))" radius={[0, 8, 8, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </div>
  );
}
