import { cn } from "@/lib/utils";

export const Card = ({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("rounded-2xl border border-border bg-card p-5 shadow-card", className)} {...p} />
);
export const Skeleton = ({ className }: { className?: string }) => (
  <div className={cn("animate-pulse rounded-xl bg-border/60", className)} aria-hidden />
);
export function EmptyState({ title, hint, action }: { title: string; hint: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-border p-10 text-center">
      <p className="font-semibold">{title}</p>
      <p className="max-w-sm text-sm text-muted">{hint}</p>
      {action}
    </div>
  );
}
