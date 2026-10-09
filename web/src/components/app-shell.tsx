"use client";
import { useQuery } from "@tanstack/react-query";
import { ChevronsLeft, ChevronsRight, LogOut } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, hasSession } from "@/lib/api";
import { useRealtime } from "@/lib/realtime";
import { cn } from "@/lib/utils";
import { CommandPalette } from "./command-palette";
import { NAV } from "./nav";
import { NotificationBell } from "./notification-bell";
import { ThemeToggle } from "./theme-toggle";
import { Button } from "./ui/button";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!hasSession()) router.replace("/login"); else setReady(true);
  }, [router]);
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, enabled: ready });
  useRealtime(ready);
  const unread = useQuery({ queryKey: ["unread"], queryFn: api.unreadCounts, enabled: ready, refetchInterval: 60_000 });
  if (!ready) return null;

  return (
    <div className="flex min-h-screen">
      <aside className={cn("sticky top-0 hidden h-screen shrink-0 flex-col border-r border-border bg-card transition-all md:flex", collapsed ? "w-16" : "w-60")}>
        <div className="flex h-14 items-center justify-between px-4 font-semibold">
          {!collapsed && <span>Freelance<span className="text-brand">Manager</span></span>}
          <button onClick={() => setCollapsed((c) => !c)} aria-label="Toggle sidebar" className="rounded-lg p-1 hover:bg-border/50">
            {collapsed ? <ChevronsRight size={16} /> : <ChevronsLeft size={16} />}
          </button>
        </div>
        <nav className="flex-1 space-y-1 overflow-auto px-2" aria-label="Main">
          {NAV.map((n) => {
            const active = pathname.startsWith(n.href);
            return (
              <Link key={n.href} href={n.href} title={n.label} aria-current={active ? "page" : undefined}
                className={cn("flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition-colors hover:bg-border/50", active && "bg-brand/10 font-medium text-brand")}>
                <n.icon size={18} /> {!collapsed && n.label}
                {n.href === "/inbox" && !!unread.data?.total && <span aria-label={`${unread.data.total} unread`} className="ml-auto rounded-full bg-brand px-1.5 text-xs text-brand-fg">{unread.data.total}</span>}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-bg/80 px-4 backdrop-blur">
          <CommandPalette />
          <div className="ml-auto flex items-center gap-1">
            <NotificationBell enabled={ready} />
            <ThemeToggle />
            <span className="hidden px-2 text-sm text-muted sm:inline">{me.data?.full_name || me.data?.email}</span>
            <Button variant="ghost" size="sm" aria-label="Log out" onClick={async () => { await api.logout(); router.replace("/login"); }}>
              <LogOut size={16} />
            </Button>
          </div>
        </header>
        <main className="flex-1 p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
