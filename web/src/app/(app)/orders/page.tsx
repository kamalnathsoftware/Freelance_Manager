"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, type Order } from "@fm/shared";
import { AlertTriangle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { PlatformBadge } from "@/components/platform-badge";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, Skeleton } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";

const STATUSES = ["active", "delivered", "revision", "completed", "cancelled"] as const;

export default function Orders() {
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState({ platform: "fiverr", title: "", amount: "" });
  const [open, setOpen] = useState<string | null>(null);
  const [ms, setMs] = useState({ title: "", amount: "" });
  const orders = useQuery({ queryKey: ["orders"], queryFn: () => api.orders() });
  const refresh = () => qc.invalidateQueries({ queryKey: ["orders"] });
  const onErr = (e: unknown) => toast(e instanceof ApiError ? e.message : "Something went wrong", "error");
  const create = useMutation({ mutationFn: () => api.createOrder({ platform: form.platform, title: form.title, amount: Number(form.amount) || 0 }), onSuccess: () => { setForm({ ...form, title: "", amount: "" }); refresh(); }, onError: onErr });
  const status = useMutation({ mutationFn: ({ id, s }: { id: string; s: string }) => api.orderStatus(id, s), onSuccess: refresh, onError: onErr });
  const toggle = useMutation({ mutationFn: ({ o, i }: { o: Order; i: number }) => api.patchOrder(o.id, { checklist: o.checklist.map((c, j) => (j === i ? { ...c, done: !c.done } : c)) }), onSuccess: refresh });
  const addMs = useMutation({ mutationFn: (id: string) => api.addMilestone(id, { title: ms.title, amount: Number(ms.amount) || 0 }), onSuccess: () => { setMs({ title: "", amount: "" }); refresh(); }, onError: onErr });
  const msAct = useMutation({ mutationFn: ({ id, mid, a }: { id: string; mid: string; a: "submit" | "pay" }) => api.milestoneAction(id, mid, a), onSuccess: refresh, onError: onErr });

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <h1 className="text-2xl font-bold">Orders &amp; contracts</h1>
      <Card>
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (form.title) create.mutate(); }}>
          <Input label="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <Input label="Platform" value={form.platform} onChange={(e) => setForm({ ...form, platform: e.target.value })} />
          <Input label="Amount" type="number" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          <Button type="submit" disabled={!form.title}>Add order</Button>
        </form>
        <p className="mt-2 text-xs text-muted">Orders are also created automatically from parsed platform emails and won proposals.</p>
      </Card>
      {orders.isLoading && <Skeleton className="h-32" />}
      {orders.data?.length === 0 && <EmptyState title="No orders yet" hint="Add one manually, forward a platform order email, or convert a won proposal." />}
      <ul className="space-y-3">
        {orders.data?.map((o) => (
          <li key={o.id}>
            <Card className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="space-y-1"><PlatformBadge platform={o.platform} /><h2 className="font-semibold">{o.title}</h2><p className="text-xs text-muted">{o.client_name || "No client"} · {o.currency} {o.amount.toLocaleString()}{o.due_at && ` · due ${new Date(o.due_at).toLocaleDateString()}`}</p></div>
                <div className="flex items-center gap-2">
                  {o.over_revision_limit && <span className="flex items-center gap-1 text-xs text-danger" title="More revisions than the order allows"><AlertTriangle size={14} />over revision limit</span>}
                  <select aria-label={`Status of ${o.title}`} value={o.status} onChange={(e) => status.mutate({ id: o.id, s: e.target.value })} className="h-8 rounded-xl border border-border bg-card px-2 text-sm">
                    {STATUSES.map((s) => <option key={s}>{s}</option>)}
                  </select>
                  <Button size="sm" variant="outline" onClick={() => setOpen(open === o.id ? null : o.id)}>{open === o.id ? "Hide" : "Details"}</Button>
                </div>
              </div>
              <p className="text-xs text-muted">Revisions {o.revisions_used}/{o.revisions_allowed}</p>
              {open === o.id && (
                <div className="grid gap-4 border-t border-border pt-3 md:grid-cols-2">
                  <div><h3 className="mb-1 text-sm font-semibold">Delivery checklist</h3>
                    <ul className="space-y-1 text-sm">{o.checklist.map((c, i) => <li key={c.item}><label className="flex items-center gap-2"><input type="checkbox" checked={c.done} onChange={() => toggle.mutate({ o, i })} /> {c.item}</label></li>)}</ul></div>
                  <div><h3 className="mb-1 text-sm font-semibold">Milestones</h3>
                    <ul className="space-y-1 text-sm">{o.milestones.map((m) => (
                      <li key={m.id} className="flex items-center justify-between gap-2"><span>{m.title} · {m.amount}</span>
                        <span className="flex items-center gap-1"><span className="text-xs text-muted">{m.status}</span>
                          {m.status !== "paid" && <Button size="sm" variant="outline" onClick={() => msAct.mutate({ id: o.id, mid: m.id, a: "pay" })}>Mark paid</Button>}</span></li>))}</ul>
                    <div className="mt-2 flex items-end gap-2"><Input label="Milestone" value={ms.title} onChange={(e) => setMs({ ...ms, title: e.target.value })} /><Input label="Amount" type="number" value={ms.amount} onChange={(e) => setMs({ ...ms, amount: e.target.value })} /><Button size="sm" disabled={!ms.title} onClick={() => addMs.mutate(o.id)}>Add</Button></div>
                  </div>
                  <div className="md:col-span-2">
                    {o.project_id ? <Link href="/projects" className="text-sm text-brand">Open project →</Link> : <Button size="sm" variant="outline" onClick={async () => { await api.orderProject(o.id); refresh(); toast("Project created"); }}>Create project from order</Button>}
                  </div>
                </div>
              )}
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
