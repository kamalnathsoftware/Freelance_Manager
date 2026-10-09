"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, type GigInput, type GigPackage } from "@fm/shared";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, Skeleton } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";

const tiers = ["basic", "standard", "premium"] as const;
const blankPkg = (tier: GigPackage["tier"]): GigPackage => ({ tier, name: "", description: "", price: 0, delivery_days: 3, revisions: 1, features: [] });
const BLANK: GigInput = { title: "", category: "", tags: [], description: "", faq: [], gallery: [], notes: "", keywords: [], status: "draft", packages: tiers.map(blankPkg) };

export default function Gigs() {
  const qc = useQueryClient();
  const toast = useToast();
  const gigs = useQuery({ queryKey: ["gigs"], queryFn: api.gigs });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts });
  const [draft, setDraft] = useState<GigInput | null>(null);
  const [tags, setTags] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["gigs"] });
  const onErr = (e: unknown) => toast(e instanceof ApiError ? e.message : "Something went wrong", "error");

  const create = useMutation({
    mutationFn: (g: GigInput) => api.createGig({ ...g, tags: tags.split(",").map((t) => t.trim()).filter(Boolean), packages: g.packages.filter((p) => p.price > 0) }),
    onSuccess: () => { setDraft(null); setTags(""); refresh(); toast("Gig saved"); }, onError: onErr,
  });
  const remove = useMutation({ mutationFn: api.deleteGig, onSuccess: refresh, onError: onErr });
  const clone = useMutation({ mutationFn: ({ id, ids }: { id: string; ids: string[] }) => api.cloneGig(id, ids), onSuccess: () => toast("Cloned to platform"), onError: onErr });

  const setPkg = (i: number, patch: Partial<GigPackage>) => setDraft((d) => d && { ...d, packages: d.packages.map((p, j) => (j === i ? { ...p, ...patch } : p)) });
  const gigAccounts = accounts.data?.filter((a) => ["fiverr", "peopleperhour", "linkedin", "direct"].includes(a.platform)) ?? [];

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Gigs</h1>
        {!draft && <Button onClick={() => setDraft(BLANK)}><Plus size={16} /> New gig</Button>}
      </div>
      {draft && (
        <Card className="space-y-4">
          <Input label="Title" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
          <p className="-mt-3 text-xs text-muted">{draft.title.length} characters (Fiverr allows 80)</p>
          <Input label="Category" value={draft.category} onChange={(e) => setDraft({ ...draft, category: e.target.value })} />
          <Input label="Tags (comma separated)" value={tags} onChange={(e) => setTags(e.target.value)} />
          <div className="space-y-1.5">
            <label htmlFor="desc" className="text-sm font-medium">Description</label>
            <textarea id="desc" rows={6} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} className="w-full rounded-xl border border-border bg-card p-3 text-sm" />
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            {draft.packages.map((p, i) => (
              <div key={p.tier} className="space-y-2 rounded-xl border border-border p-3">
                <p className="text-sm font-semibold capitalize">{p.tier}</p>
                <Input label="Name" value={p.name} onChange={(e) => setPkg(i, { name: e.target.value })} id={`name-${p.tier}`} />
                <Input label="Price" type="number" value={p.price} onChange={(e) => setPkg(i, { price: Number(e.target.value) })} id={`price-${p.tier}`} />
                <Input label="Delivery (days)" type="number" value={p.delivery_days} onChange={(e) => setPkg(i, { delivery_days: Number(e.target.value) })} id={`days-${p.tier}`} />
              </div>
            ))}
          </div>
          <div className="flex gap-2">
            <Button onClick={() => create.mutate(draft)} disabled={!draft.title || create.isPending}>Save gig</Button>
            <Button variant="ghost" onClick={() => setDraft(null)}>Cancel</Button>
          </div>
        </Card>
      )}
      {gigs.isLoading && <Skeleton className="h-24" />}
      {gigs.data?.length === 0 && !draft && <EmptyState title="No gigs yet" hint="Create a master gig, then clone it to Fiverr, PeoplePerHour and others with per-platform limits applied." />}
      <div className="space-y-3">
        {gigs.data?.map((g) => (
          <Card key={g.id} className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="font-medium">{g.title}</p>
              <p className="text-xs text-muted">{g.status} · {g.packages.length} packages · from ${Math.min(...g.packages.map((p) => p.price), Infinity) === Infinity ? 0 : Math.min(...g.packages.map((p) => p.price))}</p>
            </div>
            <div className="flex items-center gap-2">
              {gigAccounts.length > 0 && (
                <select aria-label={`Clone ${g.title} to`} defaultValue="" onChange={(e) => e.target.value && clone.mutate({ id: g.id, ids: [e.target.value] })} className="h-8 rounded-xl border border-border bg-card px-2 text-sm">
                  <option value="" disabled>Clone to…</option>
                  {gigAccounts.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
                </select>
              )}
              <Button size="sm" variant="ghost" aria-label={`Delete ${g.title}`} onClick={() => remove.mutate(g.id)}><Trash2 size={14} /></Button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
