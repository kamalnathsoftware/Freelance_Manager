"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@fm/shared";
import { RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { PlatformBadge } from "@/components/platform-badge";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, Skeleton } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";

export default function Platforms() {
  const qc = useQueryClient();
  const toast = useToast();
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: api.platformCatalog });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts });
  const [platform, setPlatform] = useState("fiverr");
  const [username, setUsername] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["accounts"] });
  const onErr = (e: unknown) => toast(e instanceof ApiError ? e.message : "Something went wrong", "error");

  const add = useMutation({ mutationFn: () => api.addAccount({ platform, username }), onSuccess: () => { setUsername(""); refresh(); toast("Account added"); }, onError: onErr });
  const sync = useMutation({ mutationFn: api.syncAccount, onSuccess: (l) => { refresh(); toast(`Sync ${l.status}: ${l.message}`); }, onError: onErr });
  const remove = useMutation({ mutationFn: api.removeAccount, onSuccess: refresh, onError: onErr });

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <h1 className="text-2xl font-bold">Platforms</h1>
      <Card>
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
          <div className="space-y-1.5">
            <label htmlFor="platform" className="text-sm font-medium">Platform</label>
            <select id="platform" value={platform} onChange={(e) => setPlatform(e.target.value)} className="h-10 rounded-xl border border-border bg-card px-3 text-sm">
              {catalog.data?.map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}
            </select>
          </div>
          <Input label="Username (optional)" value={username} onChange={(e) => setUsername(e.target.value)} />
          <Button type="submit" disabled={add.isPending}>Add account</Button>
        </form>
        <p className="mt-3 text-xs text-muted">
          Only Upwork and Freelancer.com offer official APIs. Others work through your notification emails and assisted/manual tools — we never log in or bid on your behalf.
        </p>
      </Card>
      {accounts.isLoading && <Skeleton className="h-32" />}
      {accounts.data?.length === 0 && <EmptyState title="No platforms yet" hint="Add your first platform account above to start tracking messages, orders and earnings." />}
      <div className="grid gap-4 md:grid-cols-2">
        {accounts.data?.map((a) => (
          <Card key={a.id} className="space-y-3">
            <div className="flex items-center justify-between">
              <PlatformBadge platform={a.platform} />
              <span className="text-xs text-muted">{a.integration_status}</span>
            </div>
            <p className="font-medium">{a.label}{a.username && <span className="text-muted"> · {a.username}</span>}</p>
            <dl className="grid grid-cols-4 gap-2 text-center text-sm">
              {(["unread", "active_orders", "pending_bids", "earnings"] as const).map((k) => (
                <div key={k}><dt className="text-xs text-muted">{k.replace("_", " ")}</dt><dd className="font-semibold">{a.stats[k] ?? 0}</dd></div>
              ))}
            </dl>
            {a.last_error && <p role="alert" className="text-xs text-danger">{a.last_error}</p>}
            <p className="text-xs text-muted">Last sync: {a.last_synced_at ? new Date(a.last_synced_at).toLocaleString() : "never"}</p>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => sync.mutate(a.id)}><RefreshCw size={14} /> Sync</Button>
              <Button size="sm" variant="ghost" aria-label={`Remove ${a.label}`} onClick={() => remove.mutate(a.id)}><Trash2 size={14} /></Button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
