"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@fm/shared";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, EmptyState } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { download } from "@/lib/download";

const KIND_COLOR: Record<string, string> = { order_due: "bg-danger", milestone_due: "bg-danger", task_due: "bg-brand", invoice_due: "bg-success", follow_up: "bg-muted", interview: "bg-brand", meeting: "bg-brand" };

export default function CalendarPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [ev, setEv] = useState({ title: "", starts_at: "" });
  const items = useQuery({ queryKey: ["calendar"], queryFn: api.calendar });
  const onErr = (e: unknown) => toast(e instanceof ApiError ? e.message : "Something went wrong", "error");
  const add = useMutation({ mutationFn: () => api.addCalendarEvent({ title: ev.title, kind: "meeting", starts_at: new Date(ev.starts_at).toISOString() }), onSuccess: () => { setEv({ title: "", starts_at: "" }); qc.invalidateQueries({ queryKey: ["calendar"] }); }, onError: onErr });
  const sync = useMutation({ mutationFn: api.googleCalendarSync, onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["calendar"] }); toast(`Synced: ${r.pushed} sent, ${r.pulled} received`); }, onError: onErr });
  const days = new Map<string, NonNullable<typeof items.data>>();
  items.data?.forEach((i) => { const d = new Date(i.start).toDateString(); days.set(d, [...(days.get(d) ?? []), i]); });

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <h1 className="text-2xl font-bold">Calendar</h1>
      <Card className="space-y-3">
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (ev.title && ev.starts_at) add.mutate(); }}>
          <Input label="Event" value={ev.title} onChange={(e) => setEv({ ...ev, title: e.target.value })} /><Input label="Starts" type="datetime-local" value={ev.starts_at} onChange={(e) => setEv({ ...ev, starts_at: e.target.value })} /><Button type="submit" disabled={!ev.title || !ev.starts_at}>Add</Button></form>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={() => download("/calendar/export.ics", "freelance-manager.ics")}>Download .ics</Button>
          <Button size="sm" variant="outline" onClick={async () => { const { url } = await api.calendarFeedUrl(); await navigator.clipboard.writeText(url); toast("Subscription URL copied - paste it into Google/Apple/Outlook calendar"); }}>Copy subscription URL</Button>
          <Button size="sm" variant="outline" onClick={async () => { try { window.location.href = (await api.googleCalendarAuthUrl()).url; } catch (e) { onErr(e); } }}>Connect Google Calendar</Button>
          <Button size="sm" variant="outline" onClick={() => sync.mutate()}>Sync now</Button>
        </div>
      </Card>
      {items.data?.length === 0 && <EmptyState title="Nothing scheduled" hint="Deadlines from orders, tasks, invoices and follow-ups appear here automatically." />}
      {[...days.entries()].map(([day, list]) => (
        <section key={day}><h2 className="mb-2 text-sm font-semibold text-muted">{day}</h2>
          <ul className="space-y-2">{list.map((i) => (
            <li key={i.id}><Link href={i.href} className="flex items-center gap-3 rounded-xl border border-border bg-card px-3 py-2 text-sm shadow-card hover:border-brand">
              <span className={`h-2.5 w-2.5 rounded-full ${KIND_COLOR[i.kind] ?? "bg-muted"}`} aria-hidden /><span className="flex-1">{i.title}</span>
              <span className="text-xs text-muted">{i.all_day ? "all day" : new Date(i.start).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span></Link></li>
          ))}</ul></section>
      ))}
    </div>
  );
}
