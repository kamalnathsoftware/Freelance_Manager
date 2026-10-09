"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, STAGES, type Proposal, type Stage } from "@fm/shared";
import Link from "next/link";
import { useState } from "react";
import { PlatformBadge } from "@/components/platform-badge";
import { Skeleton } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function Pipeline() {
  const qc = useQueryClient();
  const toast = useToast();
  const board = useQuery({ queryKey: ["pipeline"], queryFn: api.pipeline });
  const [over, setOver] = useState<Stage | null>(null);
  const move = useMutation({
    mutationFn: ({ id, stage, reason }: { id: string; stage: Stage; reason?: string }) => api.moveProposal(id, stage, reason),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pipeline"] }),
    onError: (e) => toast(e instanceof ApiError ? e.message : "Could not move", "error"),
  });

  const drop = (stage: Stage, e: React.DragEvent) => {
    e.preventDefault(); setOver(null);
    const id = e.dataTransfer.getData("text/plain");
    if (!id) return;
    let reason = "";
    if (stage === "lost") { reason = window.prompt("Why was this lost?") ?? ""; if (!reason) return; }
    move.mutate({ id, stage, reason });
  };

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Pipeline</h1>
      {board.isLoading && <Skeleton className="h-64" />}
      <div className="flex gap-3 overflow-x-auto pb-4">
        {STAGES.map((s) => (
          <section key={s} aria-label={s} onDragOver={(e) => { e.preventDefault(); setOver(s); }} onDragLeave={() => setOver(null)} onDrop={(e) => drop(s, e)}
            className={cn("w-64 shrink-0 rounded-2xl border border-border bg-card/60 p-3 transition-colors", over === s && "border-brand bg-brand/5")}>
            <h2 className="mb-2 flex justify-between text-sm font-semibold capitalize">{s}<span className="text-muted">{board.data?.[s]?.length ?? 0}</span></h2>
            <ul className="space-y-2">
              {board.data?.[s]?.map((p: Proposal) => (
                <li key={p.id} draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", p.id)} className="cursor-grab rounded-xl border border-border bg-card p-3 text-sm shadow-card active:cursor-grabbing">
                  <Link href={`/proposals/${p.id}`} className="font-medium hover:text-brand">{p.job_title}</Link>
                  <div className="mt-1 flex items-center justify-between"><PlatformBadge platform={p.platform} />{p.bid_amount != null && <span className="text-xs text-muted">${p.bid_amount}</span>}</div>
                  {p.lost_reason && <p className="mt-1 text-xs text-danger">{p.lost_reason}</p>}
                  {/* keyboard-accessible alternative to drag and drop */}
                  <select aria-label={`Move ${p.job_title}`} value={p.stage} onChange={(e) => {
                    const st = e.target.value as Stage; let reason = "";
                    if (st === "lost") { reason = window.prompt("Why was this lost?") ?? ""; if (!reason) return; }
                    move.mutate({ id: p.id, stage: st, reason });
                  }} className="mt-2 h-7 w-full rounded-lg border border-border bg-card px-1 text-xs">
                    {STAGES.map((x) => <option key={x}>{x}</option>)}
                  </select>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
