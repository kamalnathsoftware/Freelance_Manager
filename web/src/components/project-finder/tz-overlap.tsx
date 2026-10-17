"use client";
import { useQuery } from "@tanstack/react-query";
import type { PFTzOverlap } from "@fm/shared";
import { Clock } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const TONE: Record<PFTzOverlap["rating"], string> = {
  good: "border-success text-success", workable: "border-brand text-brand", limited: "border-border text-muted", none: "border-danger text-danger",
};
const LABEL: Record<PFTzOverlap["rating"], string> = { good: "Good overlap", workable: "Some overlap", limited: "Little overlap", none: "No overlap" };

/** Compact chip for cards. */
export function OverlapBadge({ o }: { o: PFTzOverlap }) {
  return (
    <span title={o.note} className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs", TONE[o.rating])}>
      <Clock size={12} aria-hidden />{LABEL[o.rating]} · {o.overlap_hours}h
    </span>
  );
}

/** Full explanation, shown under the time-zone field. Fetches live so it updates while typing a zone. */
export function OverlapPanel({ timezone }: { timezone: string }) {
  const tz = timezone.trim();
  const q = useQuery({ queryKey: ["pf", "tz-overlap", tz], queryFn: () => api.pfTzOverlap(tz), enabled: tz.length > 2, retry: false, staleTime: 5 * 60_000 });
  if (!tz || q.isError || !q.data) return null;
  const o = q.data;
  const ahead = o.difference_hours === 0 ? "same time as you" : `${Math.abs(o.difference_hours)} h ${o.difference_hours > 0 ? "ahead of" : "behind"} you`;
  return (
    <div className="space-y-1 rounded-xl border border-border p-3 text-xs sm:col-span-3" role="status" aria-label="Time zone overlap">
      <div className="flex flex-wrap items-center gap-2"><OverlapBadge o={o} /><span className="text-muted">{o.client_tz} (UTC{o.client_offset}) is {ahead}. It is {o.client_now} there, {o.home_now} for you.</span></div>
      {o.windows.length > 0 && (
        <ul className="text-muted">
          {o.windows.map((w) => <li key={w.home_start}>Shared hours: <b className="text-fg">{w.home_start}-{w.home_end}</b> your time = {w.client_start}-{w.client_end} theirs</li>)}
        </ul>
      )}
      <p className="text-muted">{o.note} <span className="opacity-75">(Assumes {o.hours} on both sides - change it in Settings.)</span></p>
    </div>
  );
}
