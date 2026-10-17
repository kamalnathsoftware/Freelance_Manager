"use client";
import { X } from "lucide-react";
import { useState } from "react";

/** Chips + text box. Enter or comma adds, Backspace on an empty box removes the last chip. */
export function TagInput({ label, value, onChange, placeholder, hint }: {
  label: string; value: string[]; onChange: (v: string[]) => void; placeholder?: string; hint?: string;
}) {
  const [text, setText] = useState("");
  const id = `tag-${label.toLowerCase().replace(/\W+/g, "-")}`;
  const add = (raw: string) => {
    const items = raw.split(",").map((s) => s.trim()).filter(Boolean);
    if (!items.length) return;
    const have = new Set(value.map((v) => v.toLowerCase()));
    onChange([...value, ...items.filter((i) => !have.has(i.toLowerCase()) && have.add(i.toLowerCase()))]);
    setText("");
  };
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium">{label}</label>
      <div className="flex flex-wrap gap-1.5 rounded-xl border border-border bg-card p-2">
        {value.map((v) => (
          <span key={v} className="inline-flex items-center gap-1 rounded-full bg-brand/10 px-2 py-0.5 text-xs text-brand">
            {v}
            <button type="button" aria-label={`Remove ${v}`} onClick={() => onChange(value.filter((x) => x !== v))}><X size={12} /></button>
          </span>
        ))}
        <input id={id} value={text} placeholder={value.length ? "" : placeholder} onChange={(e) => (e.target.value.endsWith(",") ? add(e.target.value) : setText(e.target.value))}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(text); } else if (e.key === "Backspace" && !text && value.length) onChange(value.slice(0, -1)); }}
          onBlur={() => add(text)} className="min-w-[8rem] flex-1 bg-transparent text-sm outline-none" />
      </div>
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  );
}
