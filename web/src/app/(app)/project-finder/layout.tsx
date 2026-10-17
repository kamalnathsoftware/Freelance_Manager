"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const PF_TABS = [
  { href: "/project-finder/jobs", label: "Jobs" },
  { href: "/project-finder/leads", label: "Leads" },
  { href: "/project-finder/templates", label: "Templates" },
  { href: "/project-finder/proposals", label: "Proposals" },
  { href: "/project-finder/stats", label: "Stats" },
  { href: "/project-finder/sources", label: "Sources" },
  { href: "/project-finder/settings", label: "Settings" },
];

export default function ProjectFinderLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="mx-auto max-w-7xl space-y-5">
      <div>
        <h1 className="text-2xl font-bold">Project Finder</h1>
        <p className="text-sm text-muted">Find and win freelance work directly - no platform fees. You send every message yourself.</p>
      </div>
      <nav aria-label="Project Finder" className="-mx-4 overflow-x-auto px-4 md:mx-0 md:px-0">
        <ul className="flex min-w-max gap-1 border-b border-border">
          {PF_TABS.map((t) => {
            const active = pathname.startsWith(t.href);
            return (
              <li key={t.href}>
                <Link href={t.href} aria-current={active ? "page" : undefined}
                  className={cn("inline-block border-b-2 px-4 py-2 text-sm", active ? "border-brand font-medium text-brand" : "border-transparent text-muted hover:text-fg")}>
                  {t.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      {children}
    </div>
  );
}
