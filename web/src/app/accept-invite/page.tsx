"use client";
import { ApiError } from "@fm/shared";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { api, hasSession } from "@/lib/api";

function Inner() {
  const token = useSearchParams().get("token");
  const [msg, setMsg] = useState("Accepting invitation…");
  const [needLogin, setNeedLogin] = useState(false);
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return;
    if (!token) { setMsg("This invitation link is incomplete."); return; }
    if (!hasSession()) { setNeedLogin(true); setMsg("Sign in (or create an account) with the email address that received the invitation, then open this link again."); return; }
    done.current = true;
    api.acceptInvite(token).then(() => setMsg("Invitation accepted. You can now switch to the shared workspace from the top bar.")).catch((e) => setMsg(e instanceof ApiError ? e.message : "Could not accept the invitation."));
  }, [token]);
  return (
    <main className="mx-auto max-w-md p-6 py-16 text-center"><p role="status">{msg}</p>
      <p className="mt-4 text-sm">{needLogin ? <><Link className="text-brand" href="/login">Sign in</Link> · <Link className="text-brand" href="/signup">Create account</Link></> : <Link className="text-brand" href="/dashboard">Go to dashboard</Link>}</p></main>
  );
}
export default function AcceptInvite() { return <Suspense><Inner /></Suspense>; }
