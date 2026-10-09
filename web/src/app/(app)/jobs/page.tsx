"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@fm/shared";
import { ExternalLink, EyeOff, Star } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { PlatformBadge } from "@/components/platform-badge";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, Skeleton } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const scoreColor = (s: number) => (s >= 70 ? "text-success" : s >= 40 ? "text-brand" : "text-muted");

export default function Jobs() {
  const qc = useQueryClient();
  const toast = useToast();
  const router = useRouter();
  const [platform, setPlatform] = useState("");
  const [minScore, setMinScore] = useState(0);
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ platform: "upwork", title: "", url: "", description: "" });
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: api.platformCatalog });
  const jobs = useQuery({ queryKey: ["jobs", platform, minScore, q], queryFn: () => api.jobs({ platform, min_score: minScore, q }) });
  const events = useQuery({ queryKey: ["events", "job_match"], queryFn: () => api.events("job_match") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["jobs"] });
  const onErr = (e: unknown) => toast(e instanceof ApiError ? e.message : "Something went wrong", "error");

  const add = useMutation({ mutationFn: () => api.addJob(form), onSuccess: () => { setAdding(false); setForm({ ...form, title: "", url: "", description: "" }); refresh(); toast("Job added"); }, onError: onErr });
  const dismiss = useMutation({ mutationFn: api.dismissJob, onSuccess: refresh, onError: onErr });
  const shortlist = useMutation({ mutationFn: api.shortlistJob, onSuccess: (r) => router.push(`/proposals/${r.proposal_id}`), onError: onErr });

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Jobs</h1>
        <Button onClick={() => setAdding((a) => !a)}>{adding ? "Close" : "Add job manually"}</Button>
      </div>
      {adding && (
        <Card className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1.5">
            <label htmlFor="jp" className="text-sm font-medium">Platform</label>
            <select id="jp" value={form.platform} onChange={(e) => setForm({ ...form, platform: e.target.value })} className="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm">
              {catalog.data?.map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}
            </select>
          </div>
          <Input label="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <Input label="Link" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
          <div className="space-y-1.5 md:col-span-2">
            <label htmlFor="jd" className="text-sm font-medium">Description</label>
            <textarea id="jd" rows={4} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="w-full rounded-xl border border-border bg-card p-3 text-sm" />
          </div>
          <Button disabled={!form.title || add.isPending} onClick={() => add.mutate()}>Save job</Button>
        </Card>
      )}
      <Card className="flex flex-wrap items-end gap-3">
        <Input label="Search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="keywords…" />
        <div className="space-y-1.5">
          <label htmlFor="pf" className="text-sm font-medium">Platform</label>
          <select id="pf" value={platform} onChange={(e) => setPlatform(e.target.value)} className="h-10 rounded-xl border border-border bg-card px-3 text-sm">
            <option value="">All</option>
            {catalog.data?.map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}
          </select>
        </div>
        <div className="space-y-1.5">
          <label htmlFor="ms" className="text-sm font-medium">Min match: {minScore}%</label>
          <input id="ms" type="range" min={0} max={100} step={10} value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} className="block" />
        </div>
      </Card>
      {!!events.data?.length && <p className="text-sm text-muted">🔔 {events.data.length} alert{events.data.length > 1 ? "s" : ""} from your saved searches</p>}
      {jobs.isLoading && <Skeleton className="h-32" />}
      {jobs.data?.length === 0 && <EmptyState title="No jobs yet" hint="Jobs arrive from platform APIs, parsed notification emails, the Chrome extension, or manual entry." />}
      <ul className="space-y-3">
        {jobs.data?.map((j) => (
          <li key={j.id}>
            <Card className="space-y-2">
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2"><PlatformBadge platform={j.platform} /><span className="text-xs text-muted">via {j.source}</span></div>
                  <h2 className="font-semibold">{j.title}</h2>
                </div>
                <div className={cn("text-right", scoreColor(j.score))} title={j.score_reasons.join("\n")}>
                  <p className="text-2xl font-bold">{j.score}%</p><p className="text-xs">match</p>
                </div>
              </div>
              <p className="line-clamp-2 text-sm text-muted">{j.description}</p>
              <p className="text-xs text-muted">{j.budget_max ? `${j.currency} ${j.budget_min ?? ""}${j.budget_min ? "–" : ""}${j.budget_max} ${j.budget_type}` : "Budget not stated"}</p>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => shortlist.mutate(j.id)}><Star size={14} /> Shortlist &amp; draft</Button>
                {j.url && <a href={j.url} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1 rounded-xl border border-border px-3 text-sm hover:bg-border/40"><ExternalLink size={14} /> Open</a>}
                <Button size="sm" variant="ghost" onClick={() => dismiss.mutate(j.id)}><EyeOff size={14} /> Dismiss</Button>
              </div>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
