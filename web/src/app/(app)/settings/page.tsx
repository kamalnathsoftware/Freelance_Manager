"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, Skeleton } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";

export default function Settings() {
  const qc = useQueryClient();
  const toast = useToast();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: api.sessions });
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");

  const revoke = useMutation({
    mutationFn: api.revokeSession,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["sessions"] }); toast("Session revoked"); },
  });

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>
      <Card className="space-y-3">
        <h2 className="font-semibold">Account</h2>
        {me.isLoading ? <Skeleton className="h-10" /> : (
          <p className="text-sm text-muted">{me.data?.email} · {me.data?.email_verified ? "verified" : "email not verified"}</p>
        )}
      </Card>
      <Card className="space-y-3">
        <h2 className="font-semibold">Two-factor authentication</h2>
        {me.data?.totp_enabled ? (
          <div className="flex items-end gap-2">
            <Input label="Code to disable" value={code} onChange={(e) => setCode(e.target.value)} />
            <Button variant="danger" onClick={async () => { try { await api.disable2fa(code); toast("2FA disabled"); setCode(""); qc.invalidateQueries({ queryKey: ["me"] }); } catch { toast("Invalid code", "error"); } }}>Disable</Button>
          </div>
        ) : setup ? (
          <div className="space-y-2 text-sm">
            <p>Add this secret to your authenticator app:</p>
            <code className="block break-all rounded-xl bg-border/50 p-2">{setup.secret}</code>
            <div className="flex items-end gap-2">
              <Input label="6-digit code" value={code} onChange={(e) => setCode(e.target.value)} />
              <Button onClick={async () => { try { await api.enable2fa(code); toast("2FA enabled"); setSetup(null); setCode(""); qc.invalidateQueries({ queryKey: ["me"] }); } catch { toast("Invalid code", "error"); } }}>Enable</Button>
            </div>
          </div>
        ) : <Button variant="outline" onClick={async () => setSetup(await api.setup2fa())}>Set up 2FA</Button>}
      </Card>
      <Card className="space-y-3">
        <h2 className="font-semibold">Devices &amp; sessions</h2>
        {sessions.isLoading && <Skeleton className="h-16" />}
        <ul className="divide-y divide-border">
          {sessions.data?.map((s) => (
            <li key={s.id} className="flex items-center justify-between py-3 text-sm">
              <div><p className="font-medium">{s.user_agent || "Unknown device"} {s.current && <span className="text-brand">(this device)</span>}</p>
                <p className="text-muted">{s.ip} · last active {new Date(s.last_used_at).toLocaleString()}</p></div>
              {!s.current && <Button size="sm" variant="outline" onClick={() => revoke.mutate(s.id)}>Revoke</Button>}
            </li>
          ))}
        </ul>
      </Card>
      <Card className="space-y-3">
        <h2 className="font-semibold">Integration status</h2>
        <p className="text-sm text-muted">Platforms appear here once connected (Connected via API · Via email · Manual).</p>
      </Card>
      <Card className="space-y-3">
        <h2 className="font-semibold">Your data</h2>
        <Button variant="outline" onClick={async () => {
          const data = await api.exportData();
          const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
          Object.assign(document.createElement("a"), { href: url, download: "freelance-manager-export.json" }).click();
        }}>Export my data</Button>
      </Card>
    </div>
  );
}
