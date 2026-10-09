"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@fm/shared";
import { Star } from "lucide-react";
import { useState } from "react";
import { PlatformBadge } from "@/components/platform-badge";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, Skeleton } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";

export default function Clients() {
  const qc = useQueryClient();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [name, setName] = useState("");
  const [mergeFrom, setMergeFrom] = useState<string | null>(null);
  const clients = useQuery({ queryKey: ["clients", q], queryFn: () => api.clients(q) });
  const refresh = () => qc.invalidateQueries({ queryKey: ["clients"] });
  const onErr = (e: unknown) => toast(e instanceof ApiError ? e.message : "Something went wrong", "error");
  const create = useMutation({ mutationFn: () => api.createClient({ name }), onSuccess: () => { setName(""); refresh(); }, onError: onErr });
  const merge = useMutation({ mutationFn: ({ target, source }: { target: string; source: string }) => api.mergeClients(target, source), onSuccess: () => { setMergeFrom(null); refresh(); toast("Clients merged"); }, onError: onErr });
  const toggleVip = useMutation({
    mutationFn: (c: NonNullable<typeof clients.data>[number]) => api.updateClient(c.id, { name: c.name, email: c.email, company: c.company, country: c.country, timezone: c.timezone, notes: c.notes, tags: c.tags, vip: !c.vip, total_earned: c.total_earned, completed_orders: c.completed_orders }),
    onSuccess: refresh, onError: onErr,
  });

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <h1 className="text-2xl font-bold">Clients</h1>
      <Card className="flex flex-wrap items-end gap-3">
        <Input label="Search" value={q} onChange={(e) => setQ(e.target.value)} />
        <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (name) create.mutate(); }}>
          <Input label="New client" value={name} onChange={(e) => setName(e.target.value)} />
          <Button type="submit" disabled={!name}>Add</Button>
        </form>
      </Card>
      {clients.isLoading && <Skeleton className="h-32" />}
      {clients.data?.length === 0 && <EmptyState title="No clients yet" hint="Clients are created automatically from incoming messages, or add one manually." />}
      {mergeFrom && <p role="status" className="rounded-xl bg-brand/10 p-3 text-sm">Choose the client to merge <strong>into</strong> - the highlighted one will be absorbed. <button className="underline" onClick={() => setMergeFrom(null)}>Cancel</button></p>}
      <div className="grid gap-4 md:grid-cols-2">
        {clients.data?.map((c) => (
          <Card key={c.id} className={mergeFrom === c.id ? "border-brand" : ""}>
            <div className="flex items-start justify-between">
              <div><h2 className="font-semibold">{c.name}{c.repeat_client && <span className="ml-2 rounded-full bg-success/15 px-2 py-0.5 text-xs text-success">repeat</span>}</h2><p className="text-sm text-muted">{c.company || c.email}</p></div>
              <Button size="sm" variant="ghost" aria-label={c.vip ? "Remove VIP" : "Mark VIP"} onClick={() => toggleVip.mutate(c)}><Star size={14} className={c.vip ? "fill-current text-brand" : ""} /></Button>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">{c.identities.map((i) => <PlatformBadge key={i.id} platform={i.platform} />)}</div>
            <p className="mt-2 text-sm">Lifetime value: <strong>${c.lifetime_value.toLocaleString()}</strong></p>
            <div className="mt-3">
              {mergeFrom && mergeFrom !== c.id
                ? <Button size="sm" onClick={() => merge.mutate({ target: c.id, source: mergeFrom })}>Merge into this client</Button>
                : !mergeFrom && <Button size="sm" variant="outline" onClick={() => setMergeFrom(c.id)}>Merge…</Button>}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
