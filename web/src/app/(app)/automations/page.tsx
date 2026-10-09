"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, type AutomationRule } from "@fm/shared";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, EmptyState } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";

type Draft = Omit<AutomationRule, "id" | "run_count" | "last_run_at"> & { id?: string };
const BLANK: Draft = { name: "", enabled: true, trigger: "job.created", conditions: [], actions: [{ type: "notify", params: { title: "{title}" } }] };

export default function Automations() {
  const qc = useQueryClient();
  const toast = useToast();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [testOut, setTestOut] = useState<string>("");
  const meta = useQuery({ queryKey: ["auto-meta"], queryFn: api.automationMeta });
  const rules = useQuery({ queryKey: ["automations"], queryFn: api.automations });
  const runs = useQuery({ queryKey: ["runs", open], queryFn: () => api.automationRuns(open!), enabled: !!open });
  const refresh = () => qc.invalidateQueries({ queryKey: ["automations"] });
  const onErr = (e: unknown) => toast(e instanceof ApiError ? e.message : "Something went wrong", "error");
  const save = useMutation({ mutationFn: (d: Draft) => api.saveAutomation(d, d.id), onSuccess: () => { setDraft(null); refresh(); toast("Rule saved"); }, onError: onErr });
  const toggle = useMutation({ mutationFn: api.toggleAutomation, onSuccess: refresh });
  const del = useMutation({ mutationFn: api.deleteAutomation, onSuccess: refresh });
  const test = useMutation({ mutationFn: ({ id, p }: { id: string; p: string }) => { let payload = {}; try { payload = JSON.parse(p || "{}"); } catch { throw new Error("Sample event must be valid JSON"); } return api.testAutomation(id, payload); }, onSuccess: (r) => setTestOut(r.matched ? `Matches. Would run:\n- ${r.actions.join("\n- ")}` : "Does not match this sample event."), onError: (e) => toast((e as Error).message, "error") });
  const [sample, setSample] = useState('{"score": 80, "title": "Example", "platform": "upwork", "budget_max": 500}');

  const setCond = (i: number, patch: Record<string, unknown>) => setDraft((d) => d && { ...d, conditions: d.conditions.map((c, j) => (j === i ? { ...c, ...patch } : c)) });
  const setAct = (i: number, patch: Partial<Draft["actions"][number]>) => setDraft((d) => d && { ...d, actions: d.actions.map((a, j) => (j === i ? { ...a, ...patch } : a)) });
  const sel = "h-9 rounded-xl border border-border bg-card px-2 text-sm";

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex items-center justify-between"><h1 className="text-2xl font-bold">Automations</h1>{!draft && <Button onClick={() => setDraft(BLANK)}><Plus size={16} /> New rule</Button>}</div>
      <p className="text-sm text-muted">If something happens and conditions match, do something. Automations never send bids or messages to clients on their own: they draft, notify, label, create tasks and queue replies for you to approve.</p>

      {draft ? (
        <Card className="space-y-4">
          <Input label="Rule name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          <div className="space-y-1.5"><label htmlFor="trg" className="text-sm font-medium">When</label>
            <select id="trg" value={draft.trigger} onChange={(e) => setDraft({ ...draft, trigger: e.target.value })} className={sel + " w-full"}>{meta.data?.triggers.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}</select></div>
          <div className="space-y-2"><p className="text-sm font-medium">Only if (all must match)</p>
            {draft.conditions.map((c, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2"><input aria-label="Field" placeholder="field e.g. score" value={c.field} onChange={(e) => setCond(i, { field: e.target.value })} className={sel} />
                <select aria-label="Operator" value={c.op} onChange={(e) => setCond(i, { op: e.target.value })} className={sel}>{meta.data?.operators.map((o) => <option key={o}>{o}</option>)}</select>
                <input aria-label="Value" value={String(c.value ?? "")} onChange={(e) => setCond(i, { value: e.target.value })} className={sel} />
                <Button size="sm" variant="ghost" aria-label="Remove condition" onClick={() => setDraft({ ...draft, conditions: draft.conditions.filter((_, j) => j !== i) })}><Trash2 size={14} /></Button></div>))}
            <Button size="sm" variant="outline" onClick={() => setDraft({ ...draft, conditions: [...draft.conditions, { field: "", op: "eq", value: "" }] })}>Add condition</Button></div>
          <div className="space-y-2"><p className="text-sm font-medium">Then</p>
            {draft.actions.map((a, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2"><select aria-label="Action" value={a.type} onChange={(e) => setAct(i, { type: e.target.value, params: {} })} className={sel}>{meta.data?.actions.map((x) => <option key={x}>{x}</option>)}</select>
                <input aria-label="Action parameters (JSON)" className={sel + " min-w-[260px] flex-1 font-mono text-xs"} value={JSON.stringify(a.params ?? {})} onChange={(e) => { try { setAct(i, { params: JSON.parse(e.target.value) }); } catch { /* keep typing */ } }} />
                <Button size="sm" variant="ghost" aria-label="Remove action" onClick={() => setDraft({ ...draft, actions: draft.actions.filter((_, j) => j !== i) })}><Trash2 size={14} /></Button></div>))}
            <Button size="sm" variant="outline" onClick={() => setDraft({ ...draft, actions: [...draft.actions, { type: "notify", params: {} }] })}>Add action</Button>
            <p className="text-xs text-muted">Parameters can use event fields like {"{title}"} or {"{platform}"}. Notify params: title, body, channels (e.g. [&quot;whatsapp&quot;,&quot;push&quot;]), urgent.</p></div>
          <div className="flex gap-2"><Button disabled={!draft.name || save.isPending} onClick={() => save.mutate(draft)}>Save rule</Button><Button variant="ghost" onClick={() => setDraft(null)}>Cancel</Button></div>
        </Card>
      ) : (
        <Card className="space-y-2"><h2 className="font-semibold">Quick start</h2>
          <div className="flex flex-wrap gap-2">{meta.data?.presets.map((p) => <Button key={p.key} size="sm" variant="outline" onClick={() => setDraft({ name: p.name, enabled: true, trigger: p.trigger, conditions: p.conditions, actions: p.actions })}>{p.name}</Button>)}</div></Card>
      )}

      {rules.data?.length === 0 && !draft && <EmptyState title="No automations yet" hint="Start from a preset above, e.g. alert me on WhatsApp and draft a proposal when a great job arrives." />}
      <ul className="space-y-3">
        {rules.data?.map((r) => (
          <li key={r.id}><Card className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div><h2 className="font-semibold">{r.name}</h2><p className="text-xs text-muted">{meta.data?.triggers.find((t) => t.key === r.trigger)?.label} · {r.conditions.length} condition(s) → {r.actions.map((a) => a.type).join(", ")} · ran {r.run_count}×</p></div>
              <div className="flex gap-1.5"><label className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={r.enabled} onChange={() => toggle.mutate(r.id)} aria-label={`${r.name} enabled`} /> on</label>
                <Button size="sm" variant="outline" onClick={() => setDraft({ id: r.id, name: r.name, enabled: r.enabled, trigger: r.trigger, conditions: r.conditions, actions: r.actions })}>Edit</Button>
                <Button size="sm" variant="outline" onClick={() => { setOpen(open === r.id ? null : r.id); setTestOut(""); }}>Test &amp; log</Button>
                <Button size="sm" variant="ghost" aria-label={`Delete ${r.name}`} onClick={() => del.mutate(r.id)}><Trash2 size={14} /></Button></div>
            </div>
            {open === r.id && (
              <div className="space-y-3 border-t border-border pt-3 text-sm">
                <label htmlFor={`s${r.id}`} className="font-medium">Sample event (JSON) - dry run, nothing is changed</label>
                <textarea id={`s${r.id}`} rows={3} value={sample} onChange={(e) => setSample(e.target.value)} className="w-full rounded-xl border border-border bg-card p-2 font-mono text-xs" />
                <Button size="sm" onClick={() => test.mutate({ id: r.id, p: sample })}>Run test</Button>
                {testOut && <pre className="whitespace-pre-wrap rounded-xl bg-border/40 p-2 text-xs">{testOut}</pre>}
                <h3 className="font-medium">Recent runs</h3>
                {runs.data?.length === 0 && <p className="text-muted">Not run yet.</p>}
                <ul className="space-y-1">{runs.data?.map((x) => <li key={x.id} className="text-xs"><span className={x.status === "error" ? "text-danger" : x.status === "ok" ? "text-success" : "text-muted"}>{x.status}</span> · {new Date(x.created_at).toLocaleString()} · {x.log.join(" | ")}</li>)}</ul>
              </div>)}
          </Card></li>
        ))}
      </ul>
    </div>
  );
}
