"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { TEMPLATE_KINDS, TEMPLATE_KIND_LABEL, type PFDraft, type PFTemplate, type PFTemplateInput, type TemplateKind } from "@fm/shared";
import { Copy, Plus, Sparkles, Wand2 } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, Skeleton } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { copyText, errMsg, fieldErrors } from "@/lib/pf";
import { cn } from "@/lib/utils";

const blank: PFTemplateInput = { name: "", kind: "cold_email", subject: "", body: "" };

export default function TemplatesPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const templates = useQuery({ queryKey: ["pf", "templates"], queryFn: api.pfTemplates });
  const [sel, setSel] = useState<string | "new" | null>(null);
  const current = sel && sel !== "new" ? templates.data?.find((t) => t.id === sel) ?? null : null;
  const starters = useMutation({
    mutationFn: api.pfAddStarters,
    onSuccess: (added) => { qc.invalidateQueries({ queryKey: ["pf", "templates"] }); toast(added.length ? `Added ${added.length} starter templates` : "Starter templates already added"); },
    onError: (e) => toast(errMsg(e), "error"),
  });

  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
      <aside className="space-y-3" aria-label="Templates">
        <Button className="w-full" onClick={() => setSel("new")}><Plus size={16} /> New template</Button>
        {templates.isLoading && <Skeleton className="h-32" />}
        {templates.isError && <Card role="alert" className="text-sm text-danger">Could not load templates. <button className="underline" onClick={() => templates.refetch()}>Retry</button></Card>}
        {templates.data?.length === 0 && (
          <EmptyState title="No templates yet" hint="Start from three ready-made templates (cold email, LinkedIn DM, proposal) and edit them to sound like you."
            action={<Button variant="outline" disabled={starters.isPending} onClick={() => starters.mutate()}>Add starter templates</Button>} />
        )}
        {TEMPLATE_KINDS.map((k) => {
          const items = templates.data?.filter((t) => t.kind === k) ?? [];
          return items.length ? (
            <section key={k} aria-label={TEMPLATE_KIND_LABEL[k]}>
              <h2 className="mb-1 px-1 text-xs font-semibold uppercase text-muted">{TEMPLATE_KIND_LABEL[k]}</h2>
              <ul className="space-y-1">
                {items.map((t) => (
                  <li key={t.id}>
                    <button onClick={() => setSel(t.id)} aria-current={sel === t.id ? "true" : undefined}
                      className={cn("w-full rounded-xl border border-border bg-card px-3 py-2 text-left text-sm hover:border-brand", sel === t.id && "border-brand bg-brand/5")}>{t.name}</button>
                  </li>
                ))}
              </ul>
            </section>
          ) : null;
        })}
      </aside>
      <div>
        {sel === null && !!templates.data?.length && <EmptyState title="Pick a template" hint="Select one on the left to edit it, fill it from a lead, or generate a personalised draft." />}
        {sel === "new" && <Editor key="new" template={null} onDone={(t) => setSel(t?.id ?? null)} />}
        {current && <Editor key={current.id} template={current} onDone={(t) => setSel(t?.id ?? null)} />}
      </div>
    </div>
  );
}

function Editor({ template, onDone }: { template: PFTemplate | null; onDone: (t: PFTemplate | null) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const [f, setF] = useState<PFTemplateInput>(template ? { name: template.name, kind: template.kind, subject: template.subject, body: template.body } : blank);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const vars = useQuery({ queryKey: ["pf", "template-vars"], queryFn: api.pfTemplateVars, staleTime: Infinity });
  const dirty = !template || template.name !== f.name || template.kind !== f.kind || template.subject !== f.subject || template.body !== f.body;

  const save = useMutation({
    mutationFn: () => (template ? api.pfUpdateTemplate(template.id, f) : api.pfCreateTemplate(f)),
    onSuccess: (t) => { qc.invalidateQueries({ queryKey: ["pf", "templates"] }); toast("Template saved"); onDone(t); },
    onError: (e) => { setErrors(fieldErrors(e)); toast(errMsg(e), "error"); },
  });
  const del = useMutation({
    mutationFn: () => api.pfDeleteTemplate(template!.id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["pf", "templates"] }); toast("Template deleted"); onDone(null); },
    onError: (e) => toast(errMsg(e), "error"),
  });
  const insert = (name: string) => {
    const el = bodyRef.current; const tag = `{{${name}}}`;
    const at = el?.selectionStart ?? f.body.length;
    setF((x) => ({ ...x, body: x.body.slice(0, at) + tag + x.body.slice(el?.selectionEnd ?? at) }));
    requestAnimationFrame(() => { el?.focus(); el?.setSelectionRange(at + tag.length, at + tag.length); });
  };

  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <form onSubmit={(e) => { e.preventDefault(); setErrors({}); save.mutate(); }} className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-[1fr_12rem]">
            <Input label="Name" value={f.name} error={errors.name} maxLength={120} onChange={(e) => setF({ ...f, name: e.target.value })} />
            <div className="space-y-1.5">
              <label htmlFor="tk" className="text-sm font-medium">Type</label>
              <select id="tk" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as TemplateKind })} className="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm">
                {TEMPLATE_KINDS.map((k) => <option key={k} value={k}>{TEMPLATE_KIND_LABEL[k]}</option>)}
              </select>
            </div>
          </div>
          {f.kind !== "linkedin_dm" && <Input label="Subject" value={f.subject} error={errors.subject} maxLength={300} onChange={(e) => setF({ ...f, subject: e.target.value })} />}
          <div className="space-y-1.5">
            <label htmlFor="tb" className="text-sm font-medium">Message</label>
            <textarea id="tb" ref={bodyRef} rows={9} value={f.body} maxLength={10000} onChange={(e) => setF({ ...f, body: e.target.value })} aria-invalid={!!errors.body} className="w-full rounded-xl border border-border bg-card p-3 text-sm" />
            {errors.body && <p role="alert" className="text-xs text-danger">{errors.body}</p>}
            <div className="flex flex-wrap gap-1.5" aria-label="Insert placeholder">
              {Object.entries(vars.data ?? {}).map(([k, desc]) => (
                <button type="button" key={k} title={desc} onClick={() => insert(k)} className="rounded-full border border-border px-2 py-0.5 font-mono text-xs hover:border-brand">{`{{${k}}}`}</button>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap justify-between gap-2">
            {template ? <Button type="button" variant="danger" disabled={del.isPending} onClick={() => { if (window.confirm(`Delete "${template.name}"?`)) del.mutate(); }}>Delete</Button> : <span />}
            <Button type="submit" disabled={!f.name.trim() || !f.body.trim() || !dirty || save.isPending}>{save.isPending ? "Saving…" : "Save template"}</Button>
          </div>
        </form>
      </Card>
      {template && <DraftPanel template={template} unsaved={dirty} />}
    </div>
  );
}

function DraftPanel({ template, unsaved }: { template: PFTemplate; unsaved: boolean }) {
  const toast = useToast();
  const leads = useQuery({ queryKey: ["pf", "leads", { q: "", dueOnly: false }], queryFn: () => api.pfLeads() });
  const [leadId, setLeadId] = useState("");
  const [instructions, setInstructions] = useState("");
  const [draft, setDraft] = useState<PFDraft | null>(null);
  const onErr = (e: unknown) => toast(errMsg(e), "error");
  const fill = useMutation({ mutationFn: () => api.pfRenderTemplate(template.id, leadId || undefined), onSuccess: setDraft, onError: onErr });
  const gen = useMutation({ mutationFn: () => api.pfGenerateDraft(template.id, leadId, instructions), onSuccess: setDraft, onError: onErr });
  const copy = async (text: string, what: string) => {
    const ok = await copyText(text);
    toast(ok ? `${what} copied` : "Could not copy - select the text and copy manually", ok ? "ok" : "error");
  };

  return (
    <Card className="space-y-3" aria-label="Draft">
      <h2 className="flex items-center gap-2 font-semibold"><Wand2 size={16} aria-hidden /> Draft a message</h2>
      <p className="text-xs text-muted">Drafts are never sent. Review, copy, and send them yourself. {unsaved && "Save the template first - drafts use the saved version."}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <label htmlFor="dl" className="text-sm font-medium">For lead</label>
          <select id="dl" value={leadId} onChange={(e) => setLeadId(e.target.value)} className="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm">
            <option value="">(no lead - fill my name only)</option>
            {leads.data?.map((l) => <option key={l.id} value={l.id}>{l.business_name}</option>)}
          </select>
        </div>
        <Input label="Extra instructions for AI (optional)" value={instructions} maxLength={500} onChange={(e) => setInstructions(e.target.value)} placeholder="e.g. mention I can start next week" />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={unsaved || fill.isPending} onClick={() => fill.mutate()}>Fill placeholders</Button>
        <Button disabled={unsaved || !leadId || gen.isPending} title={leadId ? undefined : "Pick a lead to personalise for"} onClick={() => gen.mutate()}><Sparkles size={14} /> {gen.isPending ? "Generating…" : "Generate draft with AI"}</Button>
      </div>
      {draft && (
        <div className="space-y-2">
          {!!(draft.missing.length || draft.unknown.length) && (
            <p role="status" className="rounded-xl border border-danger px-3 py-2 text-xs text-danger">
              {draft.missing.length > 0 && <>Not filled (no data): {draft.missing.map((m) => `{{${m}}}`).join(", ")}. </>}
              {draft.unknown.length > 0 && <>Unknown placeholders: {draft.unknown.map((m) => `{{${m}}}`).join(", ")}.</>}
            </p>
          )}
          {draft.ai_generated && <p className="text-xs text-muted">AI-generated - check every claim before you send.</p>}
          {draft.subject && (
            <div className="flex items-end gap-2">
              <div className="flex-1"><Input label="Subject" value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} /></div>
              <Button variant="outline" aria-label="Copy subject" onClick={() => copy(draft.subject, "Subject")}><Copy size={14} /></Button>
            </div>
          )}
          <label htmlFor="dbody" className="text-sm font-medium">Message</label>
          <textarea id="dbody" rows={10} value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} className="w-full rounded-xl border border-border bg-card p-3 text-sm" />
          <Button onClick={() => copy(draft.body, "Message")}><Copy size={14} /> Copy message</Button>
        </div>
      )}
    </Card>
  );
}
