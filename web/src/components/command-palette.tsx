"use client";
import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { NAV } from "./nav";

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen((o) => !o); }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => { if (open) { setQ(""); setIdx(0); setTimeout(() => input.current?.focus(), 0); } }, [open]);

  const results = useMemo(() => NAV.filter((n) => n.label.toLowerCase().includes(q.toLowerCase())), [q]);
  const go = (href: string) => { setOpen(false); router.push(href); };

  return (
    <>
      <button onClick={() => setOpen(true)} className="flex h-9 w-full max-w-sm items-center gap-2 rounded-xl border border-border bg-card px-3 text-sm text-muted">
        <Search size={14} /> <span className="flex-1 text-left">Search…</span>
        <kbd className="rounded border border-border px-1.5 text-xs">⌘K</kbd>
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[15vh]" onClick={() => setOpen(false)}>
          <div role="dialog" aria-label="Command palette" className="w-full max-w-lg overflow-hidden rounded-2xl border border-border bg-card shadow-card" onClick={(e) => e.stopPropagation()}>
            <input
              ref={input} value={q} onChange={(e) => { setQ(e.target.value); setIdx(0); }} placeholder="Jump to…" aria-label="Search commands"
              className="h-12 w-full border-b border-border bg-transparent px-4 text-sm"
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") setIdx((i) => Math.min(i + 1, results.length - 1));
                if (e.key === "ArrowUp") setIdx((i) => Math.max(i - 1, 0));
                if (e.key === "Enter" && results[idx]) go(results[idx].href);
              }}
            />
            <ul className="max-h-72 overflow-auto p-2">
              {results.map((r, i) => (
                <li key={r.href}>
                  <button onClick={() => go(r.href)} className={`flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm ${i === idx ? "bg-border/60" : ""}`}>
                    <r.icon size={16} /> {r.label}
                  </button>
                </li>
              ))}
              {results.length === 0 && <li className="px-3 py-6 text-center text-sm text-muted">No results</li>}
            </ul>
          </div>
        </div>
      )}
    </>
  );
}
