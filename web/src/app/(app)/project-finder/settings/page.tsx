"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { PFSettings, PFSettingsInput } from "@fm/shared";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, Skeleton } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { TagInput } from "@/components/project-finder/tag-input";
import { api } from "@/lib/api";
import { COMMON_TIMEZONES, errMsg, fieldErrors } from "@/lib/pf";

export default function SettingsPage() {
  const s = useQuery({ queryKey: ["pf", "settings"], queryFn: api.pfSettings });
  if (s.isLoading) return <Skeleton className="h-64" />;
  if (s.isError || !s.data) return <Card role="alert" className="text-sm text-danger">Could not load settings. <button className="underline" onClick={() => s.refetch()}>Retry</button></Card>;
  return <Form initial={s.data} />;
}

function Form({ initial }: { initial: PFSettings }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [f, setF] = useState<PFSettingsInput>({ ...initial });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: () => api.pfSaveSettings(f),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["pf"] }); toast("Settings saved - job scores updated"); },
    onError: (e) => { setErrors(fieldErrors(e)); toast(errMsg(e), "error"); },
  });
  const num = (k: keyof PFSettingsInput, label: string, min: number, max: number, hint?: string) => (
    <div>
      <Input label={label} type="number" min={min} max={max} value={String(f[k] ?? "")} error={errors[k as string]} onChange={(e) => setF({ ...f, [k]: e.target.value === "" ? undefined : Number(e.target.value) })} />
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
  return (
    <form onSubmit={(e) => { e.preventDefault(); setErrors({}); save.mutate(); }} className="space-y-4">
      <Card className="space-y-4">
        <h2 className="font-semibold">Job matching</h2>
        <TagInput label="My skills" value={f.skills ?? []} onChange={(skills) => setF({ ...f, skills })} placeholder="python, fastapi, playwright…"
          hint="A skill in a job's title is worth far more than one in the description. These drive the fit score." />
        <TagInput label="Extra keywords" value={f.include_keywords ?? []} onChange={(include_keywords) => setF({ ...f, include_keywords })} placeholder="e.g. contract, test automation" hint="Small bonus when found." />
        <TagInput label="Exclude keywords" value={f.exclude_keywords ?? []} onChange={(exclude_keywords) => setF({ ...f, exclude_keywords })} placeholder="e.g. wordpress, php" hint="A job containing any of these scores 0 and is never stored." />
        {num("min_store_score", "Minimum score to keep a new job", 0, 100, "New jobs below this (or matching none of your skills) are skipped so the feed stays useful.")}
      </Card>
      <Card className="space-y-4">
        <h2 className="font-semibold">Outreach & clients</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="My name (for {{my_name}})" value={f.my_name ?? ""} maxLength={120} onChange={(e) => setF({ ...f, my_name: e.target.value })} />
          {num("daily_goal", "Daily outreach goal (messages)", 1, 100)}
          <div className="space-y-1.5">
            <label htmlFor="htz" className="text-sm font-medium">My time zone</label>
            <input id="htz" list="htzs" value={f.home_tz ?? ""} onChange={(e) => setF({ ...f, home_tz: e.target.value })} aria-invalid={!!errors.home_tz} className="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm" />
            <datalist id="htzs">{COMMON_TIMEZONES.map((z) => <option key={z} value={z} />)}</datalist>
            {errors.home_tz && <p role="alert" className="text-xs text-danger">{errors.home_tz}</p>}
          </div>
          <div className="grid grid-cols-2 gap-3">
            {num("work_start_hour", "Work from (hour)", 0, 23)}
            {num("work_end_hour", "Work until (hour)", 1, 24)}
          </div>
        </div>
        <p className="text-xs text-muted">Working hours are used to show time-zone overlap with foreign clients. The daily goal rolls over at midnight in your account time zone.</p>
      </Card>
      <Button type="submit" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save settings"}</Button>
    </form>
  );
}
