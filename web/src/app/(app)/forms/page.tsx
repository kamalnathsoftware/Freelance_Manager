"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, type FieldType, type FormDef, type FormFieldDef } from "@fm/shared";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, Skeleton } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { download } from "@/lib/download";

const TYPES: FieldType[] = ["text", "textarea", "email", "number", "dropdown", "radio", "checkbox", "date", "file", "rating", "agreement"];
type Draft = Pick<FormDef, "title" | "description" | "kind" | "settings" | "fields"> & { id?: string };

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").replace(/^(\d)/, "f$1").slice(0, 40) || "field";

export default function Forms() {
  const qc = useQueryClient();
  const toast = useToast();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);
  const forms = useQuery({ queryKey: ["forms"], queryFn: api.forms });
  const tpls = useQuery({ queryKey: ["form-templates"], queryFn: api.formTemplates });
  const subs = useQuery({ queryKey: ["subs", viewing], queryFn: () => api.formSubmissions(viewing!), enabled: !!viewing });
  const refresh = () => qc.invalidateQueries({ queryKey: ["forms"] });
  const onErr = (e: unknown) => toast(e instanceof ApiError ? (typeof e.details === "string" ? e.details : e.message) : "Something went wrong", "error");

  const save = useMutation({ mutationFn: (d: Draft) => (d.id ? api.saveForm(d.id, d) : api.createForm(d)), onSuccess: () => { setDraft(null); refresh(); toast("Form saved"); }, onError: onErr });
  const tpl = useMutation({ mutationFn: api.formFromTemplate, onSuccess: refresh, onError: onErr });
  const pub = useMutation({ mutationFn: ({ id, p }: { id: string; p: boolean }) => api.publishForm(id, p), onSuccess: refresh, onError: onErr });
  const del = useMutation({ mutationFn: api.deleteForm, onSuccess: refresh });

  const setField = (i: number, patch: Partial<FormFieldDef>) => setDraft((d) => d && { ...d, fields: d.fields.map((f, j) => (j === i ? { ...f, ...patch } : f)) });
  const moveField = (i: number, dir: -1 | 1) => setDraft((d) => { if (!d) return d; const f = [...d.fields]; const j = i + dir; if (j < 0 || j >= f.length) return d; [f[i], f[j]] = [f[j], f[i]]; return { ...d, fields: f }; });

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex items-center justify-between"><h1 className="text-2xl font-bold">Forms</h1>{!draft && <Button onClick={() => setDraft({ title: "", description: "", kind: "custom", settings: {}, fields: [] })}><Plus size={16} /> New form</Button>}</div>

      {draft ? (
        <Card className="space-y-4">
          <Input label="Title" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
          <Input label="Description" value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
          {(draft.kind === "nda" || Boolean(draft.settings.require_signature)) && (
            <div className="space-y-1.5"><label htmlFor="ag" className="text-sm font-medium">Agreement text (hashed into each signature)</label>
              <textarea id="ag" rows={4} className="w-full rounded-xl border border-border bg-card p-3 text-sm" value={String(draft.settings.agreement_text ?? "")} onChange={(e) => setDraft({ ...draft, settings: { ...draft.settings, agreement_text: e.target.value } })} /></div>
          )}
          <Input label="Thank-you message" value={String(draft.settings.success_message ?? "")} onChange={(e) => setDraft({ ...draft, settings: { ...draft.settings, success_message: e.target.value } })} />
          <fieldset className="flex flex-wrap gap-4 text-sm"><legend className="mb-1 font-medium">When submitted, also…</legend>
            {[["create_project", "create a project"], ["create_proposal_draft", "create a job + proposal draft"]].map(([k, l]) => (
              <label key={k} className="flex items-center gap-1.5"><input type="checkbox" checked={((draft.settings.auto_actions as string[]) ?? []).includes(k)} onChange={(e) => { const cur = new Set((draft.settings.auto_actions as string[]) ?? []); if (e.target.checked) cur.add(k); else cur.delete(k); setDraft({ ...draft, settings: { ...draft.settings, auto_actions: [...cur] } }); }} /> {l}</label>))}
            <label className="flex items-center gap-1.5"><input type="checkbox" checked={!!draft.settings.require_signature} onChange={(e) => setDraft({ ...draft, settings: { ...draft.settings, require_signature: e.target.checked } })} /> require e-signature</label>
          </fieldset>
          <ul className="space-y-3">
            {draft.fields.map((f, i) => (
              <li key={i} className="space-y-2 rounded-xl border border-border p-3">
                <div className="flex flex-wrap items-end gap-2">
                  <Input label="Label" value={f.label} onChange={(e) => setField(i, { label: e.target.value, key: f.key && draft.id ? f.key : slug(e.target.value) })} />
                  <div className="space-y-1.5"><label htmlFor={`t${i}`} className="text-sm font-medium">Type</label><select id={`t${i}`} value={f.type} onChange={(e) => setField(i, { type: e.target.value as FieldType })} className="h-10 rounded-xl border border-border bg-card px-2 text-sm">{TYPES.map((t) => <option key={t}>{t}</option>)}</select></div>
                  <label className="flex items-center gap-1.5 pb-2 text-sm"><input type="checkbox" checked={f.required} onChange={(e) => setField(i, { required: e.target.checked })} /> required</label>
                  <div className="ml-auto flex pb-1"><Button size="sm" variant="ghost" aria-label="Move up" onClick={() => moveField(i, -1)}><ArrowUp size={14} /></Button><Button size="sm" variant="ghost" aria-label="Move down" onClick={() => moveField(i, 1)}><ArrowDown size={14} /></Button><Button size="sm" variant="ghost" aria-label="Remove field" onClick={() => setDraft({ ...draft, fields: draft.fields.filter((_, j) => j !== i) })}><Trash2 size={14} /></Button></div>
                </div>
                {(f.type === "dropdown" || f.type === "radio") && <Input label="Options (comma separated)" value={f.options.join(", ")} onChange={(e) => setField(i, { options: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} />}
                {i > 0 && (
                  <div className="flex flex-wrap items-center gap-2 text-sm"><span className="text-muted">Show only if</span>
                    <select aria-label="Condition field" value={f.show_if?.field ?? ""} onChange={(e) => setField(i, { show_if: e.target.value ? { field: e.target.value, op: f.show_if?.op ?? "eq", value: f.show_if?.value ?? "" } : null })} className="h-8 rounded-lg border border-border bg-card px-1"><option value="">always</option>{draft.fields.slice(0, i).map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}</select>
                    {f.show_if && (<><select aria-label="Operator" value={f.show_if.op} onChange={(e) => setField(i, { show_if: { ...f.show_if!, op: e.target.value } })} className="h-8 rounded-lg border border-border bg-card px-1">{["eq", "ne", "contains", "gt", "lt", "filled"].map((o) => <option key={o}>{o}</option>)}</select>
                      {f.show_if.op !== "filled" && <input aria-label="Value" value={String(f.show_if.value ?? "")} onChange={(e) => setField(i, { show_if: { ...f.show_if!, value: e.target.value } })} className="h-8 rounded-lg border border-border bg-card px-2" />}</>)}
                  </div>)}
              </li>))}
          </ul>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => setDraft({ ...draft, fields: [...draft.fields, { key: `field_${draft.fields.length + 1}`, type: "text", label: "", required: false, options: [], show_if: null }] })}><Plus size={14} /> Add field</Button>
            <Button disabled={!draft.title || save.isPending} onClick={() => save.mutate({ ...draft, fields: draft.fields.map((f, i) => ({ ...f, label: f.label || `Question ${i + 1}`, key: f.key || slug(f.label) })) })}>Save form</Button>
            <Button variant="ghost" onClick={() => setDraft(null)}>Cancel</Button>
          </div>
        </Card>
      ) : (
        <Card className="space-y-2"><h2 className="font-semibold">Start from a template</h2>
          <div className="flex flex-wrap gap-2">{tpls.data?.map((t) => <Button key={t.key} size="sm" variant="outline" title={t.description} onClick={() => tpl.mutate(t.key)}>{t.title}</Button>)}</div></Card>
      )}

      {forms.isLoading && <Skeleton className="h-24" />}
      {forms.data?.length === 0 && !draft && <EmptyState title="No forms yet" hint="Pick a template above or build your own - briefs, revision requests, onboarding, reviews, NDAs." />}
      <ul className="space-y-3">
        {forms.data?.map((f) => (
          <li key={f.id}><Card className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div><h2 className="font-semibold">{f.title} <span className={f.published ? "text-xs text-success" : "text-xs text-muted"}>{f.published ? "● live" : "○ draft"}</span></h2><p className="text-xs text-muted">{f.fields.length} fields · {f.submission_count} submissions · v{f.version}</p></div>
              <div className="flex flex-wrap gap-1.5">
                <Button size="sm" variant="outline" onClick={() => setDraft({ id: f.id, title: f.title, description: f.description, kind: f.kind, settings: f.settings, fields: f.fields })}>Edit</Button>
                <Button size="sm" variant="outline" onClick={() => pub.mutate({ id: f.id, p: !f.published })}>{f.published ? "Unpublish" : "Publish"}</Button>
                {f.published && <><Button size="sm" variant="outline" onClick={async () => { await navigator.clipboard.writeText(f.public_url); toast("Link copied"); }}>Copy link</Button><Button size="sm" variant="outline" onClick={async () => { await navigator.clipboard.writeText(f.embed_snippet); toast("Embed code copied"); }}>Copy embed</Button></>}
                <Button size="sm" variant="outline" onClick={() => setViewing(viewing === f.id ? null : f.id)}>Submissions</Button>
                <Button size="sm" variant="ghost" aria-label={`Delete ${f.title}`} onClick={() => del.mutate(f.id)}><Trash2 size={14} /></Button>
              </div>
            </div>
            {viewing === f.id && (
              <div className="space-y-2 border-t border-border pt-3">
                <Button size="sm" variant="outline" onClick={() => download(`/forms/${f.id}/submissions.csv`, "submissions.csv")}>Export CSV</Button>
                {subs.data?.length === 0 && <p className="text-sm text-muted">No submissions yet.</p>}
                {subs.data?.map((s) => (
                  <div key={s.id} className="rounded-xl border border-border p-3 text-sm"><p className="font-medium">{s.submitter_name || "Anonymous"} <span className="text-xs text-muted">{s.submitter_email} · {new Date(s.created_at).toLocaleString()}</span></p>
                    <dl className="mt-1 grid gap-x-4 sm:grid-cols-2">{Object.entries(s.answers).map(([k, v]) => <div key={k}><dt className="text-xs text-muted">{f.fields.find((x) => x.key === k)?.label ?? k}</dt><dd>{String(v)}</dd></div>)}</dl>
                    {s.signature && <Button size="sm" variant="outline" className="mt-2" onClick={() => download(`/forms/submissions/${s.id}/certificate.pdf`, "signature.pdf")}>Signed by {String(s.signature.typed_name)} - certificate</Button>}
                  </div>))}
              </div>)}
          </Card></li>
        ))}
      </ul>
    </div>
  );
}
