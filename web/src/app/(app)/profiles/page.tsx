"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, type MasterProfile } from "@fm/shared";
import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { PlatformBadge } from "@/components/platform-badge";
import { Button } from "@/components/ui/button";
import { Card, Skeleton } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";

const EMPTY: MasterProfile = {
  name: "", headline: "", bio: "", skills: [], languages: [], hourly_rate: null, currency: "USD",
  location: "", timezone: "", availability: "", certifications: [], education: [], experience: [],
};

export default function Profiles() {
  const qc = useQueryClient();
  const toast = useToast();
  const master = useQuery({ queryKey: ["master"], queryFn: api.master });
  const comp = useQuery({ queryKey: ["completeness"], queryFn: () => api.completeness() });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts });
  const variants = useQuery({ queryKey: ["variants"], queryFn: api.platformProfiles });
  const [form, setForm] = useState<MasterProfile>(EMPTY);
  const [skills, setSkills] = useState("");
  const [tone, setTone] = useState("professional");
  const [suggestion, setSuggestion] = useState<{ kind: "headline" | "bio"; text: string } | null>(null);

  useEffect(() => { if (master.data) { setForm(master.data); setSkills(master.data.skills.join(", ")); } }, [master.data]);
  const onErr = (e: unknown) => toast(e instanceof ApiError ? e.message : "Something went wrong", "error");
  const refresh = () => ["master", "completeness", "variants"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));

  const save = useMutation({
    mutationFn: () => api.saveMaster({ ...form, skills: skills.split(",").map((s) => s.trim()).filter(Boolean) }),
    onSuccess: () => { refresh(); toast("Master profile saved"); }, onError: onErr,
  });
  const derive = useMutation({ mutationFn: api.derivePlatformProfile, onSuccess: () => { refresh(); toast("Platform profile updated"); }, onError: onErr });
  const ai = useMutation({
    mutationFn: (kind: "headline" | "bio") => api.aiRewrite({ kind, text: form[kind], tone }),
    onSuccess: (s, kind) => setSuggestion({ kind, text: s.text }), onError: onErr,
  });
  const set = <K extends keyof MasterProfile>(k: K, v: MasterProfile[K]) => setForm((f) => ({ ...f, [k]: v }));

  if (master.isLoading) return <Skeleton className="h-96" />;
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <h1 className="text-2xl font-bold">Profiles</h1>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="space-y-4 lg:col-span-2">
          <h2 className="font-semibold">Master profile</h2>
          <Input label="Name" value={form.name} onChange={(e) => set("name", e.target.value)} />
          <Input label="Headline" value={form.headline} onChange={(e) => set("headline", e.target.value)} />
          <div className="space-y-1.5">
            <label htmlFor="bio" className="text-sm font-medium">Bio</label>
            <textarea id="bio" rows={6} value={form.bio} onChange={(e) => set("bio", e.target.value)} className="w-full rounded-xl border border-border bg-card p-3 text-sm" />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select aria-label="Tone" value={tone} onChange={(e) => setTone(e.target.value)} className="h-8 rounded-xl border border-border bg-card px-2 text-sm">
              {["professional", "friendly", "confident", "concise", "persuasive"].map((t) => <option key={t}>{t}</option>)}
            </select>
            <Button size="sm" variant="outline" disabled={!form.headline} onClick={() => ai.mutate("headline")}><Sparkles size={14} /> Rewrite headline</Button>
            <Button size="sm" variant="outline" disabled={!form.bio} onClick={() => ai.mutate("bio")}><Sparkles size={14} /> Rewrite bio</Button>
          </div>
          {suggestion && (
            <div className="rounded-xl border border-brand/40 bg-brand/5 p-3 text-sm">
              <p className="mb-1 text-xs font-medium text-brand">AI suggestion — review before applying</p>
              <p className="whitespace-pre-wrap">{suggestion.text}</p>
              <div className="mt-2 flex gap-2">
                <Button size="sm" onClick={() => { set(suggestion.kind, suggestion.text); setSuggestion(null); }}>Apply</Button>
                <Button size="sm" variant="ghost" onClick={() => setSuggestion(null)}>Discard</Button>
              </div>
            </div>
          )}
          <Input label="Skills (comma separated)" value={skills} onChange={(e) => setSkills(e.target.value)} />
          <div className="grid gap-4 sm:grid-cols-3">
            <Input label="Hourly rate" type="number" value={form.hourly_rate ?? ""} onChange={(e) => set("hourly_rate", e.target.value === "" ? null : Number(e.target.value))} />
            <Input label="Location" value={form.location} onChange={(e) => set("location", e.target.value)} />
            <Input label="Timezone" value={form.timezone} onChange={(e) => set("timezone", e.target.value)} />
          </div>
          <Input label="Availability" value={form.availability} onChange={(e) => set("availability", e.target.value)} />
          <Button onClick={() => save.mutate()} disabled={save.isPending}>Save master profile</Button>
        </Card>
        <Card className="space-y-3">
          <h2 className="font-semibold">Completeness</h2>
          <p className="text-3xl font-bold">{comp.data?.score ?? 0}%</p>
          <div className="h-2 rounded-full bg-border"><div className="h-2 rounded-full bg-brand transition-all" style={{ width: `${comp.data?.score ?? 0}%` }} /></div>
          <ul className="space-y-1 text-sm">
            {comp.data?.checklist.map((c) => <li key={c.item} className={c.done ? "text-muted line-through" : ""}>{c.done ? "✓" : "○"} {c.item}</li>)}
          </ul>
        </Card>
      </div>
      <Card className="space-y-3">
        <h2 className="font-semibold">Platform variants</h2>
        {accounts.data?.length === 0 && <p className="text-sm text-muted">Add a platform account first.</p>}
        <ul className="divide-y divide-border">
          {accounts.data?.map((a) => {
            const v = variants.data?.find((x) => x.account_id === a.id);
            return (
              <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm">
                <div className="space-y-1"><PlatformBadge platform={a.platform} />
                  {v?.violations.map((x) => <p key={x} className="text-xs text-danger">{x}</p>)}</div>
                <div className="flex items-center gap-3">
                  <span className={v?.sync_status === "drifted" ? "text-danger" : "text-muted"}>{v ? v.sync_status.replace("_", " ") : "not created"}</span>
                  <Button size="sm" variant="outline" disabled={!master.data} onClick={() => derive.mutate(a.id)}>{v ? "Re-sync from master" : "Create from master"}</Button>
                </div>
              </li>
            );
          })}
        </ul>
      </Card>
    </div>
  );
}
