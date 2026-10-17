"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { JobStatus, PFJob, PFJobQuery, PFRefreshResult } from "@fm/shared";
import { Bookmark, ExternalLink, EyeOff, RefreshCw, Undo2, UserPlus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, Skeleton } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { errMsg, timeAgo } from "@/lib/pf";
import { cn } from "@/lib/utils";

const scoreColor = (s: number) => (s >= 70 ? "text-success" : s >= 40 ? "text-brand" : "text-muted");
const PAGE = 30;

export default function JobsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [kw, setKw] = useState<string[]>([]);
  const [source, setSource] = useState("");
  const [minScore, setMinScore] = useState(0);
  const [remote, setRemote] = useState(false);
  const [status, setStatus] = useState<"active" | "saved" | "dismissed">("active");
  const [sort, setSort] = useState<"score" | "date">("score");
  const [limit, setLimit] = useState(PAGE);
  const [results, setResults] = useState<PFRefreshResult[] | null>(null);

  const query: PFJobQuery = { q, keywords: kw.join(","), source, min_score: minScore, remote: remote || undefined, status, sort, limit };
  const settings = useQuery({ queryKey: ["pf", "settings"], queryFn: api.pfSettings });
  const sources = useQuery({ queryKey: ["pf", "sources"], queryFn: api.pfSources });
  const jobs = useQuery({ queryKey: ["pf", "jobs", query], queryFn: () => api.pfJobs(query), placeholderData: (prev) => prev });
  const reload = () => qc.invalidateQueries({ queryKey: ["pf", "jobs"] });
  const onErr = (e: unknown) => toast(errMsg(e), "error");

  const refresh = useMutation({
    mutationFn: () => api.pfRefreshJobs(),
    onSuccess: (r) => {
      setResults(r); reload(); qc.invalidateQueries({ queryKey: ["pf", "sources"] });
      const fresh = r.reduce((n, x) => n + x.new, 0), bad = r.filter((x) => x.status === "error").length, skipped = r.filter((x) => x.status === "skipped").length;
      toast(`${fresh} new job${fresh === 1 ? "" : "s"}${bad ? `, ${bad} source${bad > 1 ? "s" : ""} failed` : ""}${skipped ? `, ${skipped} checked recently` : ""}`, bad ? "error" : "ok");
    },
    onError: onErr,
  });
  const setJob = useMutation({ mutationFn: ({ id, s }: { id: string; s: JobStatus }) => api.pfUpdateJob(id, s), onSuccess: reload, onError: onErr });
  const toLead = useMutation({ mutationFn: api.pfJobToLead, onSuccess: (l) => { reload(); qc.invalidateQueries({ queryKey: ["pf", "leads"] }); toast("Added to Leads"); router.push(`/project-finder/leads?lead=${l.id}`); }, onError: onErr });

  const toggleKw = (k: string) => { setKw((x) => (x.includes(k) ? x.filter((y) => y !== k) : [...x, k])); setLimit(PAGE); };
  const feedSources = sources.data?.filter((s) => s.kind === "feed") ?? [];
  const filtered = !!(q || kw.length || source || minScore || remote);

  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Input label="Search" value={q} onChange={(e) => { setQ(e.target.value); setLimit(PAGE); }} placeholder="title, company, text…" />
          <div className="space-y-1.5">
            <label htmlFor="js" className="text-sm font-medium">Source</label>
            <select id="js" value={source} onChange={(e) => { setSource(e.target.value); setLimit(PAGE); }} className="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm">
              <option value="">All sources</option>
              {feedSources.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
            </select>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="jm" className="text-sm font-medium">Min fit score: {minScore}</label>
            <input id="jm" type="range" min={0} max={100} step={10} value={minScore} onChange={(e) => { setMinScore(Number(e.target.value)); setLimit(PAGE); }} className="block h-10 w-full" />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="jo" className="text-sm font-medium">Sort by</label>
            <select id="jo" value={sort} onChange={(e) => setSort(e.target.value as "score" | "date")} className="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm">
              <option value="score">Best fit</option><option value="date">Newest</option>
            </select>
          </div>
        </div>
        {!!settings.data?.skills.length && (
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Keyword filters">
            <span className="text-xs text-muted">Keywords:</span>
            {settings.data.skills.slice(0, 14).map((k) => (
              <button key={k} type="button" aria-pressed={kw.includes(k)} onClick={() => toggleKw(k)}
                className={cn("rounded-full border px-2.5 py-0.5 text-xs", kw.includes(k) ? "border-brand bg-brand/10 text-brand" : "border-border text-muted hover:border-brand")}>{k}</button>
            ))}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={remote} onChange={(e) => setRemote(e.target.checked)} /> Remote only</label>
          <div className="flex gap-1" role="group" aria-label="Show">
            {(["active", "saved", "dismissed"] as const).map((s) => <Button key={s} size="sm" variant={status === s ? "primary" : "outline"} aria-pressed={status === s} onClick={() => { setStatus(s); setLimit(PAGE); }}>{s === "active" ? "Inbox" : s[0].toUpperCase() + s.slice(1)}</Button>)}
          </div>
          <Button className="ml-auto" disabled={refresh.isPending} onClick={() => refresh.mutate()}><RefreshCw size={14} className={refresh.isPending ? "animate-spin" : ""} /> {refresh.isPending ? "Fetching…" : "Refresh now"}</Button>
        </div>
      </Card>

      {results && (
        <Card className="space-y-1 text-sm" role="status" aria-label="Refresh results">
          <div className="flex justify-between"><b>Last refresh</b><button className="text-xs text-muted underline" onClick={() => setResults(null)}>Dismiss</button></div>
          <ul className="grid gap-x-6 sm:grid-cols-2">
            {results.map((r) => (
              <li key={r.key} className={cn("flex justify-between gap-2 text-xs", r.status === "error" ? "text-danger" : "text-muted")}>
                <span>{r.name}</span><span className="text-right">{r.status === "ok" ? `${r.new} new / ${r.fetched} fetched` : r.message}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {jobs.isLoading && <Skeleton className="h-40" />}
      {jobs.isError && <Card role="alert" className="text-sm text-danger">Could not load jobs. <button className="underline" onClick={() => jobs.refetch()}>Retry</button></Card>}
      {jobs.data?.length === 0 && (
        filtered ? <EmptyState title="No jobs match these filters" hint="Lower the minimum score or clear the keyword filters." />
          : status !== "active" ? <EmptyState title={`Nothing ${status} yet`} hint="Jobs you save or dismiss from the inbox appear here." />
          : <EmptyState title="No jobs yet" hint="Press “Refresh now” to fetch jobs from the public feeds (We Work Remotely, RemoteOK, Remotive, Hacker News, Reddit). Only jobs matching your skills are kept - tune them under Settings."
              action={<Button disabled={refresh.isPending} onClick={() => refresh.mutate()}><RefreshCw size={14} /> Refresh now</Button>} />
      )}
      <ul className="space-y-3">
        {jobs.data?.map((j) => <JobCard key={j.id} j={j} busy={setJob.isPending || toLead.isPending} onStatus={(s) => setJob.mutate({ id: j.id, s })} onLead={() => toLead.mutate(j.id)} />)}
      </ul>
      {jobs.data && jobs.data.length >= limit && <div className="text-center"><Button variant="outline" onClick={() => setLimit((l) => l + PAGE)}>Load more</Button></div>}
    </div>
  );
}

function JobCard({ j, busy, onStatus, onLead }: { j: PFJob; busy: boolean; onStatus: (s: JobStatus) => void; onLead: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <li>
      <Card className="space-y-2">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <p className="text-xs text-muted">{j.source_name} · {timeAgo(j.posted_at ?? j.created_at)}{j.remote && " · Remote"}</p>
            <h2 className="font-semibold">{j.title}</h2>
            {j.company && <p className="text-sm text-muted">{j.company}</p>}
          </div>
          <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label={`Fit score ${j.fit_score} out of 100. Show why`} className={cn("shrink-0 text-right", scoreColor(j.fit_score))}>
            <span className="block text-2xl font-bold">{j.fit_score}</span><span className="block text-xs underline decoration-dotted">fit</span>
          </button>
        </div>
        {open && <ul className="rounded-xl bg-border/30 p-3 text-xs text-muted">{j.score_reasons.map((r) => <li key={r}>• {r}</li>)}</ul>}
        <p className={cn("whitespace-pre-line text-sm text-muted", !open && "line-clamp-3")}>{j.description}</p>
        {j.skills.length > 0 && <ul className="flex flex-wrap gap-1.5" aria-label="Tags">{j.skills.slice(0, 8).map((t) => <li key={t} className="rounded-full border border-border px-2 py-0.5 text-xs text-muted">{t}</li>)}</ul>}
        <div className="flex flex-wrap items-center gap-2">
          {j.budget && <span className="text-xs text-muted">{j.budget}</span>}
          <div className="ml-auto flex flex-wrap gap-2">
            {j.url && <a href={j.url} target="_blank" rel="noopener noreferrer" className="inline-flex h-8 items-center gap-1 rounded-xl border border-border px-3 text-sm hover:border-brand">View on {j.source_name} <ExternalLink size={12} aria-hidden /></a>}
            {j.status === "dismissed" ? (
              <Button size="sm" variant="outline" disabled={busy} onClick={() => onStatus("new")}><Undo2 size={14} /> Restore</Button>
            ) : (
              <>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => onStatus("dismissed")}><EyeOff size={14} /> Dismiss</Button>
                {j.status !== "saved" && <Button size="sm" variant="outline" disabled={busy} onClick={() => onStatus("saved")}><Bookmark size={14} /> Save</Button>}
                <Button size="sm" disabled={busy} onClick={onLead}><UserPlus size={14} /> Add to leads</Button>
              </>
            )}
          </div>
        </div>
      </Card>
    </li>
  );
}
