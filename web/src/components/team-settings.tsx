"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, type TeamMember } from "@fm/shared";
import { useState } from "react";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Input } from "./ui/input";
import { useToast } from "./ui/toast";
import { api } from "@/lib/api";

const ROLE_LABEL: Record<TeamMember["role"], string> = { full: "Full access", messaging_only: "Messaging only", view_only: "View only" };

export function TeamSettings() {
  const qc = useQueryClient();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<TeamMember["role"]>("messaging_only");
  const team = useQuery({ queryKey: ["team"], queryFn: api.team, retry: false });
  const refresh = () => qc.invalidateQueries({ queryKey: ["team"] });
  const onErr = (e: unknown) => toast(e instanceof ApiError ? e.message : "Something went wrong", "error");
  const invite = useMutation({ mutationFn: () => api.invite(email, role), onSuccess: () => { setEmail(""); refresh(); toast("Invitation sent"); }, onError: onErr });
  const change = useMutation({ mutationFn: ({ id, r }: { id: string; r: TeamMember["role"] }) => api.setMemberRole(id, r), onSuccess: refresh, onError: onErr });
  const remove = useMutation({ mutationFn: api.removeMember, onSuccess: refresh, onError: onErr });
  return (
    <Card className="space-y-3">
      <h2 className="font-semibold">Team &amp; virtual assistants</h2>
      <p className="text-sm text-muted">Invite someone to work in your workspace with limited permissions. They sign in with their own account; everything they do in your workspace is written to your audit log.</p>
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (email) invite.mutate(); }}>
        <Input label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <div className="space-y-1.5"><label htmlFor="inv-role" className="text-sm font-medium">Role</label>
          <select id="inv-role" value={role} onChange={(e) => setRole(e.target.value as TeamMember["role"])} className="h-10 rounded-xl border border-border bg-card px-3 text-sm">
            {(Object.keys(ROLE_LABEL) as TeamMember["role"][]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</select></div>
        <Button type="submit" disabled={!email || invite.isPending}>Invite</Button>
      </form>
      {team.data && <p className="text-xs text-muted">{ROLE_LABEL[role]}: {team.data.roles[role]}</p>}
      <ul className="divide-y divide-border text-sm">
        {team.data?.members.map((m) => (
          <li key={m.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span>{m.invite_email} <span className="text-xs text-muted">{m.accepted ? "" : "(invitation pending)"}</span></span>
            <span className="flex items-center gap-2">
              <select aria-label={`Role for ${m.invite_email}`} value={m.role} onChange={(e) => change.mutate({ id: m.id, r: e.target.value as TeamMember["role"] })} className="h-8 rounded-xl border border-border bg-card px-2 text-sm">
                {(Object.keys(ROLE_LABEL) as TeamMember["role"][]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</select>
              <Button size="sm" variant="outline" onClick={() => remove.mutate(m.id)}>Remove</Button>
            </span>
          </li>
        ))}
        {team.data?.members.length === 0 && <li className="py-2 text-muted">No team members yet.</li>}
      </ul>
    </Card>
  );
}
