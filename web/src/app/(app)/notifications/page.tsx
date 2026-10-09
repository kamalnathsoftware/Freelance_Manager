"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@fm/shared";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, EmptyState } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const statusColor: Record<string, string> = { sent: "text-success", failed: "text-danger", pending: "text-brand", digest: "text-muted", skipped: "text-muted" };

export default function Notifications() {
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<"inbox" | "log">("inbox");
  const list = useQuery({ queryKey: ["notifications-all"], queryFn: () => api.notifications() });
  const log = useQuery({ queryKey: ["deliveries"], queryFn: () => api.deliveries(), enabled: tab === "log" });
  const retry = useMutation({
    mutationFn: api.retryDelivery,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["deliveries"] }); toast("Retried"); },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Retry failed", "error"),
  });
  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <h1 className="text-2xl font-bold">Notifications</h1>
      <div role="tablist" className="flex gap-2">
        {(["inbox", "log"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={cn("rounded-xl px-3 py-1.5 text-sm", tab === t ? "bg-brand/10 text-brand" : "text-muted")}>
            {t === "inbox" ? "All notifications" : "Delivery log"}
          </button>
        ))}
      </div>
      {tab === "inbox" ? (
        <Card className="divide-y divide-border p-0">
          {list.data?.items.length === 0 && <EmptyState title="Nothing yet" hint="Events like new messages, orders and deadlines appear here." />}
          {list.data?.items.map((n) => (
            <div key={n.id} className="px-4 py-3 text-sm">
              <p className={cn("font-medium", n.read_at && "text-muted")}>{n.title}{n.priority === "high" && <span className="ml-2 rounded-full bg-danger/10 px-2 text-xs text-danger">urgent</span>}</p>
              {n.body && <p className="text-muted">{n.body}</p>}
              <p className="text-xs text-muted">{new Date(n.created_at).toLocaleString()} · {n.type.replace(/_/g, " ")}</p>
            </div>
          ))}
        </Card>
      ) : (
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted"><tr><th className="p-3">Notification</th><th>Channel</th><th>Status</th><th>Tries</th><th>Detail</th><th /></tr></thead>
            <tbody>
              {log.data?.map((d) => (
                <tr key={d.id} className="border-t border-border">
                  <td className="p-3">{d.event_title}</td>
                  <td>{d.channel}{d.fallback_of && " (fallback)"}</td>
                  <td className={statusColor[d.status]}>{d.status}</td>
                  <td>{d.attempts}</td>
                  <td className="max-w-[220px] truncate text-xs text-muted" title={d.error}>{d.error || (d.next_attempt_at ? `next try ${new Date(d.next_attempt_at).toLocaleTimeString()}` : "")}</td>
                  <td>{(d.status === "failed" || d.status === "skipped") && <Button size="sm" variant="outline" onClick={() => retry.mutate(d.id)}>Retry</Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
