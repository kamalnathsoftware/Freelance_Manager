"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "./ui/button";

export function NotificationBell({ enabled }: { enabled: boolean }) {
  const qc = useQueryClient();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const q = useQuery({ queryKey: ["notifications"], queryFn: () => api.notifications(), enabled, refetchInterval: 60_000 });
  const read = useMutation({ mutationFn: api.markRead, onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }) });
  const readAll = useMutation({ mutationFn: api.markAllRead, onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }) });
  useEffect(() => {
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const unread = q.data?.unread ?? 0;
  return (
    <div className="relative" ref={box}>
      <Button variant="ghost" size="sm" aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Bell size={16} />
        {unread > 0 && <span className="absolute -right-0.5 -top-0.5 rounded-full bg-danger px-1 text-[10px] text-white">{unread > 9 ? "9+" : unread}</span>}
      </Button>
      {open && (
        <div role="dialog" aria-label="Notifications" className="absolute right-0 mt-2 w-80 overflow-hidden rounded-2xl border border-border bg-card shadow-card">
          <div className="flex items-center justify-between border-b border-border px-3 py-2 text-sm font-semibold">
            Notifications
            <button className="text-xs font-normal text-brand" onClick={() => readAll.mutate()}>Mark all read</button>
          </div>
          <ul className="max-h-80 overflow-auto">
            {q.data?.items.slice(0, 8).map((n) => (
              <li key={n.id}>
                <button
                  className={`w-full px-3 py-2 text-left text-sm hover:bg-border/40 ${n.read_at ? "text-muted" : ""}`}
                  onClick={() => { read.mutate(n.id); setOpen(false); if (n.url.startsWith("/")) router.push(n.url); else if (n.url) window.open(n.url, "_blank", "noopener"); }}
                >
                  <p className="font-medium">{n.title}</p>
                  {n.body && <p className="line-clamp-2 text-xs">{n.body}</p>}
                </button>
              </li>
            ))}
            {q.data?.items.length === 0 && <li className="px-3 py-6 text-center text-sm text-muted">You&apos;re all caught up</li>}
          </ul>
          <Link href="/notifications" onClick={() => setOpen(false)} className="block border-t border-border px-3 py-2 text-center text-sm text-brand">View all &amp; delivery log</Link>
        </div>
      )}
    </div>
  );
}
