"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, type SubmitResult } from "@fm/shared";
import { Check, Copy, ExternalLink, Sparkles } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, Skeleton } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";

export default function ProposalBuilder() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const toast = useToast();
  const p = useQuery({ queryKey: ["proposal", id], queryFn: () => api.proposal(id) });
  const templates = useQuery({ queryKey: ["templates"], queryFn: api.templates });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts });
  const [body, setBody] = useState("");
  const [bid, setBid] = useState<string>("");
  const [manual, setManual] = useState<SubmitResult | null>(null);
  useEffect(() => { if (p.data) { setBody(p.data.body); setBid(p.data.bid_amount?.toString() ?? ""); } }, [p.data]);

  const refresh = () => qc.invalidateQueries({ queryKey: ["proposal", id] });
  const onErr = (e: unknown) => toast(e instanceof ApiError ? e.message : "Something went wrong", "error");
  const save = useMutation({ mutationFn: () => api.updateProposal(id, { body, bid_amount: bid === "" ? null : Number(bid) }), onSuccess: () => { refresh(); toast("Saved"); }, onError: onErr });
  const draft = useMutation({ mutationFn: (b: { template_id?: string; use_ai?: boolean }) => api.draftProposal(id, b), onSuccess: refresh, onError: onErr });
  const approve = useMutation({ mutationFn: async () => { await api.updateProposal(id, { body }); return api.approveProposal(id); }, onSuccess: () => { refresh(); toast("Approved - ready to submit"); }, onError: onErr });
  const submit = useMutation({
    mutationFn: () => api.submitProposal(id),
    onSuccess: (r) => { if (r.submitted) { toast("Submitted via API"); refresh(); } else setManual(r); }, onError: onErr,
  });
  const marked = useMutation({ mutationFn: () => api.markSubmitted(id), onSuccess: () => { setManual(null); refresh(); toast("Marked as submitted"); }, onError: onErr });
  const suggest = useMutation({ mutationFn: () => api.bidSuggestion(p.data!.job_id), onSuccess: (r) => { if (r.amount != null) setBid(String(r.amount)); toast(r.rationale); } });

  if (p.isLoading || !p.data) return <Skeleton className="h-96" />;
  const d = p.data;
  const submitted = ["submitted", "viewed", "interview", "won"].includes(d.stage);

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div><p className="text-sm text-muted capitalize">{d.platform} · {d.stage}</p><h1 className="text-2xl font-bold">{d.job_title}</h1></div>
      <Card className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label="Template" defaultValue="" onChange={(e) => e.target.value && draft.mutate({ template_id: e.target.value })} className="h-8 rounded-xl border border-border bg-card px-2 text-sm">
            <option value="" disabled>Fill from template…</option>
            {templates.data?.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <Button size="sm" variant="outline" disabled={draft.isPending} onClick={() => draft.mutate({ use_ai: true })}><Sparkles size={14} /> Draft with AI</Button>
          {d.ai_generated && <span className="rounded-full bg-brand/10 px-2 py-0.5 text-xs text-brand">AI-generated - review before approving</span>}
        </div>
        <textarea aria-label="Proposal text" rows={12} value={body} onChange={(e) => setBody(e.target.value)} className="w-full rounded-xl border border-border bg-card p-3 text-sm" />
        {d.unresolved_variables.length > 0 && <p role="alert" className="text-sm text-danger">Fill in: {d.unresolved_variables.map((v) => `{${v}}`).join(", ")}</p>}
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1.5"><label htmlFor="bid" className="text-sm font-medium">Bid amount</label>
            <input id="bid" type="number" value={bid} onChange={(e) => setBid(e.target.value)} className="h-10 w-32 rounded-xl border border-border bg-card px-3 text-sm" /></div>
          <Button variant="outline" size="sm" onClick={() => suggest.mutate()}>Suggest bid</Button>
          <Button variant="outline" onClick={() => save.mutate()}>Save draft</Button>
        </div>
      </Card>
      <Card className="space-y-3">
        <h2 className="font-semibold">Review &amp; submit</h2>
        <p className="text-sm text-muted">Nothing is sent without your explicit approval. Platforms without an official bidding API use the assisted flow: you paste it yourself.</p>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => approve.mutate()} disabled={!body || approve.isPending || submitted}><Check size={14} /> {d.approved_at ? "Re-approve" : "Approve"}</Button>
          <Button variant="outline" disabled={!d.approved_at || submitted || submit.isPending} onClick={() => submit.mutate()}>Submit</Button>
          {submitted && <span className="self-center text-sm text-success">Submitted {d.submitted_via && `(${d.submitted_via})`}</span>}
        </div>
        {manual && (
          <div className="space-y-2 rounded-xl border border-border p-3 text-sm">
            <p>{manual.instructions}</p>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={async () => { await navigator.clipboard.writeText(manual.proposal_text ?? ""); toast("Copied"); }}><Copy size={14} /> Copy proposal</Button>
              {manual.open_url && <a href={manual.open_url} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1 rounded-xl border border-border px-3 hover:bg-border/40"><ExternalLink size={14} /> Open on platform</a>}
              <Button size="sm" onClick={() => marked.mutate()}>Mark as submitted</Button>
            </div>
          </div>
        )}
        {accounts.data && <p className="text-xs text-muted">{accounts.data.length} connected account(s)</p>}
      </Card>
    </div>
  );
}
