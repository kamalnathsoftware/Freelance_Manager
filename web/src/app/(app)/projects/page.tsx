"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, type Task } from "@fm/shared";
import { Play, Square } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, Skeleton } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { download } from "@/lib/download";
import { cn } from "@/lib/utils";

const COLS: Task["status"][] = ["todo", "doing", "done"];

function Elapsed({ since }: { since: string }) {
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((n) => n + 1), 1000); return () => clearInterval(t); }, []);
  const s = Math.max(0, Math.floor((Date.now() - new Date(since).getTime()) / 1000));
  return <span className="tabular-nums">{String(Math.floor(s / 3600)).padStart(2, "0")}:{String(Math.floor(s / 60) % 60).padStart(2, "0")}:{String(s % 60).padStart(2, "0")}</span>;
}

export default function Projects() {
  const qc = useQueryClient();
  const toast = useToast();
  const [sel, setSel] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [rate, setRate] = useState("");
  const [title, setTitle] = useState("");
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const tasks = useQuery({ queryKey: ["tasks", sel], queryFn: () => api.tasks(sel!), enabled: !!sel });
  const running = useQuery({ queryKey: ["running"], queryFn: api.runningTimer });
  const onErr = (e: unknown) => toast(e instanceof ApiError ? e.message : "Something went wrong", "error");
  const inv = () => ["projects", "tasks", "running"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const create = useMutation({ mutationFn: () => api.createProject({ name, hourly_rate: rate ? Number(rate) : null }), onSuccess: (p) => { setName(""); setRate(""); setSel(p.id); inv(); }, onError: onErr });
  const addTask = useMutation({ mutationFn: () => api.addTask(sel!, { title }), onSuccess: () => { setTitle(""); inv(); }, onError: onErr });
  const move = useMutation({ mutationFn: ({ t, status }: { t: Task; status: Task["status"] }) => api.updateTask(t.id, { title: t.title, status, priority: t.priority }), onSuccess: inv });
  const start = useMutation({ mutationFn: (pid: string) => api.startTimer({ project_id: pid }), onSuccess: inv, onError: onErr });
  const stop = useMutation({ mutationFn: api.stopTimer, onSuccess: inv, onError: onErr });
  const bill = useMutation({ mutationFn: api.invoiceFromTime, onSuccess: (i) => toast(`Draft invoice ${i.number} created (${i.currency} ${i.total})`), onError: onErr });

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <h1 className="text-2xl font-bold">Projects</h1>
      {running.data && <p role="status" className="rounded-xl bg-brand/10 px-3 py-2 text-sm">⏱ Timer running <Elapsed since={running.data.started_at} /> <Button size="sm" className="ml-2" onClick={() => stop.mutate()}><Square size={12} /> Stop</Button></p>}
      <Card><form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (name) create.mutate(); }}>
        <Input label="New project" value={name} onChange={(e) => setName(e.target.value)} /><Input label="Hourly rate" type="number" value={rate} onChange={(e) => setRate(e.target.value)} /><Button type="submit" disabled={!name}>Create</Button></form></Card>
      {projects.isLoading && <Skeleton className="h-24" />}
      {projects.data?.length === 0 && <EmptyState title="No projects" hint="Create a project (or one from an order) to track tasks and time." />}
      <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
        <ul className="space-y-2">
          {projects.data?.map((p) => (
            <li key={p.id}><button onClick={() => setSel(p.id)} className={cn("w-full rounded-2xl border border-border bg-card p-3 text-left text-sm shadow-card", sel === p.id && "border-brand")}>
              <p className="font-medium">{p.name}</p><p className="text-xs text-muted">{p.hours_tracked}h · {p.tasks_done}/{p.tasks_total} tasks{p.hourly_rate ? ` · ${p.currency} ${p.hourly_rate}/h` : ""}</p></button></li>
          ))}
        </ul>
        {sel && (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => start.mutate(sel)}><Play size={12} /> Start timer</Button>
              <Button size="sm" variant="outline" onClick={() => download(`/time/export?project_id=${sel}`, "timesheet.csv")}>Export timesheet</Button>
              <Button size="sm" variant="outline" onClick={() => bill.mutate(sel)}>Invoice unbilled time</Button>
            </div>
            <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (title) addTask.mutate(); }}><Input label="New task" value={title} onChange={(e) => setTitle(e.target.value)} /><Button type="submit" disabled={!title}>Add</Button></form>
            <div className="grid gap-3 md:grid-cols-3">
              {COLS.map((c) => (
                <Card key={c} className="space-y-2 p-3"><h3 className="text-sm font-semibold capitalize">{c}</h3>
                  {tasks.data?.filter((t) => t.status === c).map((t) => (
                    <div key={t.id} className="rounded-xl border border-border p-2 text-sm"><p>{t.title}</p>
                      <select aria-label={`Move ${t.title}`} value={t.status} onChange={(e) => move.mutate({ t, status: e.target.value as Task["status"] })} className="mt-1 h-7 w-full rounded-lg border border-border bg-card text-xs">{COLS.map((x) => <option key={x}>{x}</option>)}</select></div>
                  ))}
                </Card>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
