import * as React from "react";
import { cn } from "@/lib/utils";

interface Props extends React.InputHTMLAttributes<HTMLInputElement> { label: string; error?: string }

export const Input = React.forwardRef<HTMLInputElement, Props>(({ label, error, className, id, ...p }, ref) => {
  const inputId = id ?? `in-${label.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <div className="space-y-1.5">
      <label htmlFor={inputId} className="text-sm font-medium">{label}</label>
      <input
        id={inputId} ref={ref} aria-invalid={!!error} aria-describedby={error ? `${inputId}-err` : undefined}
        className={cn("h-10 w-full rounded-xl border border-border bg-card px-3 text-sm placeholder:text-muted", error && "border-danger", className)}
        {...p}
      />
      {error && <p id={`${inputId}-err`} role="alert" className="text-xs text-danger">{error}</p>}
    </div>
  );
});
Input.displayName = "Input";
