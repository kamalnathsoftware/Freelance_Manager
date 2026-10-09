"use client";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, getWorkspace, setWorkspace } from "@/lib/api";

/** Lets an invited member switch between their own workspace and workspaces they were invited to. */
export function WorkspaceSwitcher({ enabled }: { enabled: boolean }) {
  const [current, setCurrent] = useState<string>("");
  const ws = useQuery({ queryKey: ["workspaces"], queryFn: api.workspaces, enabled });
  useEffect(() => { setCurrent(getWorkspace() ?? ""); }, []);
  if (!ws.data || ws.data.length < 2) return null;
  const self = ws.data.find((w) => w.is_self)!;
  return (
    <div className="flex items-center gap-1.5">
      <label htmlFor="ws-switch" className="sr-only">Workspace</label>
      <select
        id="ws-switch" value={current || self.owner_id}
        onChange={(e) => { const id = e.target.value; setWorkspace(id === self.owner_id ? null : id); window.location.reload(); }}
        className="h-9 max-w-[180px] rounded-xl border border-border bg-card px-2 text-sm"
      >
        {ws.data.map((w) => <option key={w.owner_id} value={w.owner_id}>{w.is_self ? "My workspace" : `${w.name} (${w.role.replace("_", " ")})`}</option>)}
      </select>
    </div>
  );
}
