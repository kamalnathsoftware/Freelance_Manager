"use client";
import { useState } from "react";
import { PlatformBadge } from "@/components/platform-badge";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, Skeleton } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { SERIES } from "@/components/charts";

/** Living style guide (our Storybook equivalent): every core component in every state, in light and dark.
 *  Public on purpose so designers/QA can review it without logging in. */
export default function DesignSystem() {
  const toast = useToast();
  const [v, setV] = useState("");
  return (
    <main className="mx-auto max-w-4xl space-y-8 p-6">
      <header className="flex items-center justify-between"><h1 className="text-3xl font-bold">Design system</h1><ThemeToggle /></header>
      <section aria-labelledby="ds-buttons" className="space-y-3"><h2 id="ds-buttons" className="text-xl font-semibold">Buttons</h2>
        <div className="flex flex-wrap gap-2">
          <Button>Primary</Button><Button variant="outline">Outline</Button><Button variant="ghost">Ghost</Button><Button variant="danger">Danger</Button><Button disabled>Disabled</Button>
          <Button size="sm">Small</Button><Button size="lg">Large</Button>
        </div></section>
      <section aria-labelledby="ds-inputs" className="space-y-3"><h2 id="ds-inputs" className="text-xl font-semibold">Inputs</h2>
        <div className="grid gap-4 sm:grid-cols-2"><Input label="Default" placeholder="Type here" value={v} onChange={(e) => setV(e.target.value)} /><Input label="With error" error="This field is required" /><Input label="Disabled" disabled value="Locked" readOnly /></div></section>
      <section aria-labelledby="ds-cards" className="space-y-3"><h2 id="ds-cards" className="text-xl font-semibold">Cards, loading &amp; empty states</h2>
        <div className="grid gap-4 sm:grid-cols-2"><Card><p className="font-semibold">Card</p><p className="text-sm text-muted">Rounded-2xl, subtle shadow, 8-pt spacing.</p></Card><Card className="space-y-2"><Skeleton className="h-5 w-1/2" /><Skeleton className="h-4" /><Skeleton className="h-4 w-3/4" /></Card></div>
        <EmptyState title="Nothing here yet" hint="Empty states explain what will appear and offer the next step." action={<Button size="sm">Create something</Button>} /></section>
      <section aria-labelledby="ds-feedback" className="space-y-3"><h2 id="ds-feedback" className="text-xl font-semibold">Feedback</h2>
        <div className="flex gap-2"><Button variant="outline" onClick={() => toast("Saved successfully")}>Success toast</Button><Button variant="outline" onClick={() => toast("Something went wrong", "error")}>Error toast</Button></div></section>
      <section aria-labelledby="ds-badges" className="space-y-3"><h2 id="ds-badges" className="text-xl font-semibold">Platform badges</h2>
        <div className="flex flex-wrap gap-2">{["upwork", "fiverr", "freelancer", "peopleperhour", "toptal", "guru", "linkedin", "contra", "direct"].map((p) => <PlatformBadge key={p} platform={p} />)}</div></section>
      <section aria-labelledby="ds-colors" className="space-y-3"><h2 id="ds-colors" className="text-xl font-semibold">Colour tokens</h2>
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">{[["bg-bg", ""], ["bg-card", ""], ["bg-brand", "text-white"], ["bg-danger", "text-white"], ["bg-success", "text-white"], ["bg-border", ""]].map(([c, t]) => <div key={c} className={`${c} ${t} h-14 rounded-xl border border-border text-center text-xs leading-[3.5rem]`}>{c.slice(3)}</div>)}</div>
        <div className="flex gap-2" aria-label="Chart series colours">{SERIES.map((c) => <span key={c} className="h-6 w-6 rounded-full" style={{ background: c }} title={c} />)}</div></section>
    </main>
  );
}
