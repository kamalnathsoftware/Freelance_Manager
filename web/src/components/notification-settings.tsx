"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, type NotificationPrefs } from "@fm/shared";
import { useState } from "react";
import { Button } from "./ui/button";
import { Card, Skeleton } from "./ui/card";
import { Input } from "./ui/input";
import { useToast } from "./ui/toast";
import { api } from "@/lib/api";
import { enableWebPush } from "@/lib/webpush";

const CH_LABEL: Record<string, string> = { in_app: "In-app", push: "Push", email: "Email", whatsapp: "WhatsApp", sms: "SMS", telegram: "Telegram" };

export function NotificationSettings() {
  const qc = useQueryClient();
  const toast = useToast();
  const prefs = useQuery({ queryKey: ["prefs"], queryFn: api.notificationPrefs });
  const channels = useQuery({ queryKey: ["channels"], queryFn: api.channels });
  const [quiet, setQuiet] = useState<{ s?: string; e?: string }>({});
  const [phone, setPhone] = useState<Record<string, string>>({});
  const onErr = (e: unknown) => toast(e instanceof ApiError ? e.message : "Something went wrong", "error");
  const save = useMutation({ mutationFn: api.saveNotificationPrefs, onSuccess: (d) => { qc.setQueryData(["prefs"], d); toast("Preferences saved"); }, onError: onErr });
  const test = useMutation({ mutationFn: api.testNotification, onSuccess: (r) => toast(`Test ${r.status}${r.error ? `: ${r.error}` : ""}`, r.status === "sent" ? "ok" : "error"), onError: onErr });

  const set = (t: string, ch: string, patch: Partial<NotificationPrefs["matrix"][string][string]>) => {
    const cur = prefs.data!.matrix[t][ch];
    save.mutate({ matrix: { [t]: { [ch]: { ...cur, ...patch } } } });
  };
  if (prefs.isLoading || !prefs.data) return <Skeleton className="h-48" />;
  const p = prefs.data;
  return (
    <>
      <Card className="space-y-3">
        <h2 className="font-semibold">Notification channels</h2>
        <ul className="space-y-3">
          {channels.data?.filter((c) => c.channel !== "email").map((c) => (
            <li key={c.channel} className="flex flex-wrap items-end gap-2 text-sm">
              <Input label={`${CH_LABEL[c.channel]} ${c.channel === "telegram" ? "chat id" : "number"}`} value={phone[c.channel] ?? c.address} onChange={(e) => setPhone({ ...phone, [c.channel]: e.target.value })} placeholder={c.channel === "telegram" ? "linked via bot" : "+15551234567"} />
              <label className="flex items-center gap-1.5 pb-2"><input type="checkbox" checked={c.opted_in} onChange={async (e) => { try { await api.saveChannel({ channel: c.channel, address: phone[c.channel] ?? c.address, opted_in: e.target.checked }); qc.invalidateQueries({ queryKey: ["channels"] }); } catch (err) { onErr(err); } }} /> I agree to receive messages (opt-in)</label>
              {c.channel === "telegram" && <Button size="sm" variant="outline" onClick={async () => toast((await api.telegramLink()).instructions)}>Get link code</Button>}
              <Button size="sm" variant="outline" onClick={() => test.mutate(c.channel)}>Send test</Button>
              {!c.server_configured && <span className="pb-2 text-xs text-muted">Not configured on this server</span>}
            </li>
          ))}
        </ul>
        <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => test.mutate("email")}>Test email</Button><Button size="sm" variant="outline" onClick={() => test.mutate("in_app")}>Test in-app</Button><Button size="sm" variant="outline" onClick={async () => toast((await enableWebPush()) ? "Browser push enabled" : "Browser push unavailable (permission denied or not configured)")}>Enable browser push</Button></div>
      </Card>
      <Card className="space-y-3">
        <h2 className="font-semibold">Quiet hours &amp; digests</h2>
        <div className="flex flex-wrap items-end gap-3">
          <Input label="Quiet from" type="time" value={quiet.s ?? p.settings.quiet_start} onChange={(e) => setQuiet({ ...quiet, s: e.target.value })} />
          <Input label="Until" type="time" value={quiet.e ?? p.settings.quiet_end} onChange={(e) => setQuiet({ ...quiet, e: e.target.value })} />
          <Button onClick={() => save.mutate({ quiet_start: quiet.s ?? p.settings.quiet_start, quiet_end: quiet.e ?? p.settings.quiet_end })}>Save</Button>
        </div>
        <p className="text-xs text-muted">Urgent items (VIP clients, clients waiting past your SLA) always come through immediately. Quiet hours use your profile timezone.</p>
      </Card>
      <Card className="space-y-3 overflow-x-auto">
        <h2 className="font-semibold">What to notify, and where</h2>
        <table className="w-full min-w-[640px] text-sm">
          <thead className="text-left text-xs text-muted"><tr><th className="py-2">Event</th>{p.channels.map((c) => <th key={c} className="px-2">{CH_LABEL[c]}</th>)}</tr></thead>
          <tbody>
            {p.event_types.map((t) => (
              <tr key={t.type} className="border-t border-border">
                <td className="py-2">{t.label}</td>
                {p.channels.map((c) => {
                  const cell = p.matrix[t.type][c];
                  return (
                    <td key={c} className="px-2">
                      <input type="checkbox" aria-label={`${t.label} via ${CH_LABEL[c]}`} checked={cell.enabled} onChange={(e) => set(t.type, c, { enabled: e.target.checked })} />
                      {cell.enabled && c !== "in_app" && (
                        <select aria-label={`${t.label} ${CH_LABEL[c]} frequency`} value={cell.mode} onChange={(e) => set(t.type, c, { mode: e.target.value as "instant" })} className="ml-1 rounded border border-border bg-card text-xs">
                          <option value="instant">instant</option><option value="hourly">hourly</option><option value="daily">daily</option>
                        </select>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}
