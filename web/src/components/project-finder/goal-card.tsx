"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Flame, Minus, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, Skeleton } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { errMsg } from "@/lib/pf";
import { cn } from "@/lib/utils";

/** Daily outreach goal + streak. "+1" records a message you sent yourself; the app never sends anything. */
export function GoalCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const goal = useQuery({ queryKey: ["pf", "goal"], queryFn: api.pfGoal });
  const set = (g: unknown) => { qc.setQueryData(["pf", "goal"], g); qc.invalidateQueries({ queryKey: ["pf", "leads"] }); };
  const add = useMutation({ mutationFn: () => api.pfLogOutreach({}), onSuccess: set, onError: (e) => toast(errMsg(e), "error") });
  const undo = useMutation({ mutationFn: api.pfUndoOutreach, onSuccess: set, onError: (e) => toast(errMsg(e), "error") });

  if (goal.isLoading) return <Skeleton className="h-24" />;
  if (goal.isError || !goal.data) return <Card className="text-sm text-danger" role="alert">Could not load your daily goal. <button className="underline" onClick={() => goal.refetch()}>Retry</button></Card>;
  const g = goal.data;
  const pct = Math.min(100, Math.round((g.today / g.goal) * 100));
  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm text-muted">Today&apos;s outreach</p>
          <p className="text-2xl font-bold">{g.today}<span className="text-base font-normal text-muted"> / {g.goal}</span></p>
        </div>
        <div className="flex items-center gap-1 text-sm" title={`Best streak: ${g.best_streak} days`}>
          <Flame size={18} className={g.streak ? "text-brand" : "text-muted"} aria-hidden />
          <span className="font-semibold">{g.streak}</span><span className="text-muted">day streak</span>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" aria-label="Undo last message" disabled={!g.today || undo.isPending} onClick={() => undo.mutate()}><Minus size={14} /></Button>
          <Button size="sm" disabled={add.isPending} onClick={() => add.mutate()}><Plus size={14} /> Message sent</Button>
        </div>
      </div>
      <div role="progressbar" aria-valuemin={0} aria-valuemax={g.goal} aria-valuenow={Math.min(g.today, g.goal)} aria-label="Daily outreach progress" className="h-2 overflow-hidden rounded-full bg-border/60">
        <div className={cn("h-full rounded-full transition-all", g.goal_met ? "bg-success" : "bg-brand")} style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs text-muted">{g.goal_met ? "Goal reached - nice. Keep the streak alive tomorrow." : `${g.remaining} more to hit today's goal.`}</p>
      <ul className="flex gap-1" aria-label="Last 14 days">
        {g.days.map((d) => <li key={d.date} title={`${d.date}: ${d.count}`} className={cn("h-2 flex-1 rounded-sm", d.met ? "bg-success" : d.count ? "bg-brand/40" : "bg-border/60")} />)}
      </ul>
    </Card>
  );
}
