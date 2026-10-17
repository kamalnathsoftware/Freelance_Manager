"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { PFSource } from "@fm/shared";
import { ExternalLink, Pause, Play, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, Skeleton } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { errMsg, fieldErrors, timeAgo } from "@/lib/pf";
import { cn } from "@/lib/utils";

export default function SourcesPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const sources = useQuery({ queryKey: ["pf", "sources"], queryFn: api.pfSources });
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", url: "", notes: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const refresh = () => qc.invalidateQueries({ queryKey: ["pf", "sources"] });
  const onErr = (e: unknown) => toast(errMsg(e), "error");
  const update = useMutation({ mutationFn: ({ id, ...b }: { id: string } & Partial<Pick<PFSource, "status" | "notes">>) => api.pfUpdateSource(id, b), onSuccess: refresh, onError: onErr });
  const checked = useMutation({ mutationFn: api.pfMarkChecked, onSuccess: refresh, onError: onErr });
  const del = useMutation({ mutationFn: api.pfDeleteSource, onSuccess: () => { refresh(); toast("Source removed"); }, onError: onErr });
  const add = useMutation({
    mutationFn: () => api.pfAddSource(form),
    onSuccess: () => { refresh(); setAdding(false); setForm({ name: "", url: "", notes: "" }); toast("Source added"); },
    onError: (e) => { setErrors(fieldErrors(e)); onErr(e); },
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-2xl text-sm text-muted">Where to look for work without paying platform fees. <b>Auto</b> sources are read from their public RSS/API feeds on a schedule (respecting robots.txt). <b>Manual</b> sources are links you open yourself - nothing is scraped.</p>
        <Button onClick={() => setAdding((a) => !a)}><Plus size={16} /> {adding ? "Close" : "Add source"}</Button>
      </div>
      {adding && (
        <Card>
          <form onSubmit={(e) => { e.preventDefault(); setErrors({}); add.mutate(); }} className="grid gap-3 sm:grid-cols-2">
            <Input label="Name" value={form.name} error={errors.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <Input label="Link" value={form.url} error={errors.url} placeholder="https://…" onChange={(e) => setForm({ ...form, url: e.target.value })} />
            <div className="sm:col-span-2"><Input label="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></div>
            <Button type="submit" disabled={!form.name.trim() || !form.url.trim() || add.isPending}>Save source</Button>
          </form>
        </Card>
      )}
      {sources.isLoading && <Skeleton className="h-48" />}
      {sources.isError && <Card role="alert" className="text-sm text-danger">Could not load sources. <button className="underline" onClick={() => sources.refetch()}>Retry</button></Card>}
      {sources.data?.length === 0 && <EmptyState title="No sources" hint="Add a job board or community you check regularly." />}
      <ul className="grid gap-3 md:grid-cols-2">
        {sources.data?.map((s) => (
          <li key={s.id}>
            <Card className={cn("flex h-full flex-col gap-2", s.status === "paused" && "opacity-70")}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h2 className="truncate font-semibold">{s.name}</h2>
                  <span className={cn("rounded-full border px-2 py-0.5 text-xs", s.kind === "feed" ? "border-brand text-brand" : "border-border text-muted")}>{s.kind === "feed" ? "Auto feed" : "Manual"}</span>
                  {s.status === "paused" && <span className="ml-1 rounded-full border border-border px-2 py-0.5 text-xs text-muted">Paused</span>}
                </div>
                <a href={s.url} target="_blank" rel="noopener noreferrer" onClick={() => s.kind === "manual" && checked.mutate(s.id)}
                  className="inline-flex shrink-0 items-center gap-1 rounded-xl border border-border px-3 py-1.5 text-sm hover:border-brand" aria-label={`Open ${s.name}`}>Open <ExternalLink size={14} aria-hidden /></a>
              </div>
              {s.hint && <p className="text-xs text-muted">{s.hint}</p>}
              <p className={cn("text-xs", s.last_result.startsWith("error") ? "text-danger" : "text-muted")}>
                Last checked {timeAgo(s.last_checked_at)}{s.last_result && ` - ${s.last_result}`}
              </p>
              <label className="sr-only" htmlFor={`n-${s.id}`}>Notes for {s.name}</label>
              <textarea id={`n-${s.id}`} rows={2} defaultValue={s.notes} placeholder="Notes (saved when you click away)" maxLength={2000}
                onBlur={(e) => { if (e.target.value !== s.notes) update.mutate({ id: s.id, notes: e.target.value }); }} className="w-full rounded-xl border border-border bg-card p-2 text-sm" />
              <div className="mt-auto flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => update.mutate({ id: s.id, status: s.status === "active" ? "paused" : "active" })}>
                  {s.status === "active" ? <><Pause size={14} /> Pause</> : <><Play size={14} /> Resume</>}
                </Button>
                {s.kind === "manual" && <Button size="sm" variant="outline" disabled={checked.isPending} onClick={() => checked.mutate(s.id)}>Mark checked today</Button>}
                {!s.builtin && <Button size="sm" variant="danger" aria-label={`Delete ${s.name}`} onClick={() => { if (window.confirm(`Remove ${s.name}?`)) del.mutate(s.id); }}><Trash2 size={14} /></Button>}
              </div>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
