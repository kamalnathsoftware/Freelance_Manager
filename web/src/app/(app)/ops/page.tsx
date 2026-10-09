"use client";
import { useQuery } from "@tanstack/react-query";
import { Card, EmptyState, Skeleton } from "@/components/ui/card";
import { api } from "@/lib/api";

export default function Ops() {
  const q = useQuery({ queryKey: ["ops"], queryFn: api.ops, refetchInterval: 30_000, retry: false });
  if (q.isError) return <EmptyState title="Admins only" hint="Add your email to ADMIN_EMAILS on the server to see background-job health." />;
  const d = q.data;
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <h1 className="text-2xl font-bold">Operations</h1>
      {!d ? <Skeleton className="h-40" /> : (<>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[["Database", d.db_ok ? "OK" : "DOWN"], ["Celery workers", String(d.celery.online)], ["Pending deliveries", String(d.pending_deliveries)], ["Users", String(d.users)]].map(([l, v]) => <Card key={l}><p className="text-sm text-muted">{l}</p><p className="text-2xl font-bold">{v}</p></Card>)}
        </div>
        {Object.entries(d.last_24h).map(([k, v]) => <Card key={k}><h2 className="font-semibold capitalize">{k.replace("_", " ")} (24h)</h2><p className="text-sm text-muted">{Object.entries(v).map(([s, n]) => `${s}: ${n}`).join(" · ") || "none"}</p></Card>)}
        {Object.entries(d.recent_failures).map(([k, rows]) => (
          <Card key={k}><h2 className="font-semibold capitalize">Recent failures: {k.replace("_", " ")}</h2>
            {rows.length === 0 ? <p className="text-sm text-muted">None 🎉</p> : <ul className="mt-2 space-y-1 text-xs">{rows.map((r) => <li key={String(r.id)} className="font-mono">{JSON.stringify(r)}</li>)}</ul>}</Card>
        ))}
      </>)}
    </div>
  );
}
