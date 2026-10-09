"use client";
import type { FormFieldDef, PublicForm } from "@fm/shared";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const base = `${API}/api/v1/public/forms`;

function met(c: FormFieldDef["show_if"], a: Record<string, unknown>) {
  if (!c) return true;
  const v = a[c.field];
  switch (c.op) {
    case "filled": return v !== undefined && v !== "" && v !== false;
    case "ne": return String(v) !== String(c.value);
    case "contains": return String(v ?? "").toLowerCase().includes(String(c.value).toLowerCase());
    case "gt": return Number(v) > Number(c.value);
    case "lt": return Number(v) < Number(c.value);
    default: return typeof v === "boolean" ? v === Boolean(c.value) : String(v) === String(c.value);
  }
}

function Inner() {
  const { key } = useParams<{ key: string }>();
  const embed = useSearchParams().get("embed") === "1";
  const [form, setForm] = useState<PublicForm | null>(null);
  const [missing, setMissing] = useState(false);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [sigName, setSigName] = useState("");
  const [honey, setHoney] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch(`${base}/${key}`).then(async (r) => (r.ok ? setForm(await r.json()) : setMissing(true))).catch(() => setMissing(true));
  }, [key]);

  // hidden fields are neither shown nor required (the server re-checks everything)
  const visible = useMemo(() => {
    const shown: FormFieldDef[] = [];
    const eff: Record<string, unknown> = {};
    for (const f of form?.fields ?? []) {
      if (met(f.show_if, eff)) { shown.push(f); if (f.key in answers) eff[f.key] = answers[f.key]; }
    }
    return shown;
  }, [form, answers]);

  const set = (k: string, v: unknown) => setAnswers((a) => ({ ...a, [k]: v }));

  async function upload(k: string, file: File | undefined) {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch(`${base}/${key}/upload`, { method: "POST", body: fd });
    if (r.ok) { set(k, (await r.json()).file_id); setErrors((e) => ({ ...e, [k]: "" })); }
    else setErrors((e) => ({ ...e, [k]: r.status === 413 ? "File is too large" : r.status === 415 ? "This file type is not allowed" : "Upload failed" }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErrors({});
    const body = { answers: Object.fromEntries(visible.map((f) => [f.key, answers[f.key]]).filter(([, v]) => v !== undefined)), signature_name: sigName, website: honey };
    try {
      const r = await fetch(`${base}/${key}/submit`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const j = await r.json();
      if (r.ok) setDone(j.message ?? "Thanks!");
      else setErrors(j.error?.details?.errors ?? { _form: "Something went wrong" });
    } catch { setErrors({ _form: "Network error - please try again" }); }
    setBusy(false);
  }

  const wrap = (c: React.ReactNode) => <main className={embed ? "p-4" : "mx-auto max-w-xl p-4 py-10"}><div className="rounded-2xl border border-border bg-card p-6 shadow-card">{c}</div></main>;
  if (missing) return wrap(<p>This form is not available.</p>);
  if (!form) return wrap(<p className="text-muted">Loading…</p>);
  if (done) return wrap(<p role="status" className="text-lg font-medium">{done}</p>);

  const inputCls = "h-10 w-full rounded-xl border border-border bg-card px-3 text-sm";
  return wrap(
    <form onSubmit={submit} className="space-y-5" noValidate>
      <div><h1 className="text-2xl font-bold">{form.title}</h1>{form.description && <p className="mt-1 text-muted">{form.description}</p>}</div>
      {form.requires_signature && form.agreement_text && <div className="max-h-40 overflow-auto rounded-xl border border-border bg-bg p-3 text-sm whitespace-pre-wrap">{form.agreement_text}</div>}
      {visible.map((f) => {
        const id = `f-${f.key}`;
        const err = errors[f.key];
        return (
          <div key={f.key} className="space-y-1.5">
            {f.type !== "checkbox" && f.type !== "agreement" && <label htmlFor={id} className="text-sm font-medium">{f.label}{f.required && <span aria-hidden className="text-danger"> *</span>}</label>}
            {(f.type === "text" || f.type === "email" || f.type === "number" || f.type === "date") && <input id={id} type={f.type} className={inputCls} aria-invalid={!!err} onChange={(e) => set(f.key, e.target.value)} />}
            {f.type === "textarea" && <textarea id={id} rows={4} className="w-full rounded-xl border border-border bg-card p-3 text-sm" aria-invalid={!!err} onChange={(e) => set(f.key, e.target.value)} />}
            {f.type === "dropdown" && <select id={id} className={inputCls} defaultValue="" onChange={(e) => set(f.key, e.target.value)}><option value="" disabled>Choose…</option>{f.options.map((o) => <option key={o}>{o}</option>)}</select>}
            {f.type === "radio" && <div role="radiogroup" aria-label={f.label} className="space-y-1">{f.options.map((o) => <label key={o} className="flex items-center gap-2 text-sm"><input type="radio" name={id} onChange={() => set(f.key, o)} /> {o}</label>)}</div>}
            {(f.type === "checkbox" || f.type === "agreement") && <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" onChange={(e) => set(f.key, e.target.checked)} /> <span>{f.label}{f.required && <span aria-hidden className="text-danger"> *</span>}</span></label>}
            {f.type === "rating" && <div role="radiogroup" aria-label={f.label} className="flex gap-1">{[1, 2, 3, 4, 5].map((n) => <button type="button" key={n} aria-label={`${n} star${n > 1 ? "s" : ""}`} aria-pressed={answers[f.key] === n} onClick={() => set(f.key, n)} className={`text-2xl ${(answers[f.key] as number) >= n ? "text-brand" : "text-border"}`}>★</button>)}</div>}
            {f.type === "file" && <input id={id} type="file" className="text-sm" onChange={(e) => upload(f.key, e.target.files?.[0])} />}
            {f.help_text && <p className="text-xs text-muted">{f.help_text}</p>}
            {err && <p role="alert" className="text-xs text-danger">{err}</p>}
          </div>
        );
      })}
      {form.requires_signature && (
        <div className="space-y-1.5"><label htmlFor="sig" className="text-sm font-medium">Type your full name to sign <span aria-hidden className="text-danger">*</span></label>
          <input id="sig" className={inputCls} value={sigName} onChange={(e) => setSigName(e.target.value)} />{errors._signature && <p role="alert" className="text-xs text-danger">{errors._signature}</p>}</div>
      )}
      {/* honeypot: hidden from people and assistive tech; bots fill it */}
      <div aria-hidden="true" style={{ position: "absolute", left: "-9999px" }}><label>Website<input tabIndex={-1} autoComplete="off" value={honey} onChange={(e) => setHoney(e.target.value)} /></label></div>
      {(errors._form || errors._email) && <p role="alert" className="text-sm text-danger">{errors._form || errors._email}</p>}
      <button disabled={busy} className="h-11 w-full rounded-xl bg-brand font-medium text-brand-fg disabled:opacity-50">{busy ? "Sending…" : "Submit"}</button>
    </form>,
  );
}

export default function PublicFormPage() { return <Suspense><Inner /></Suspense>; }
