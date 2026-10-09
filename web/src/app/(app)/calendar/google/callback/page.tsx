"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

function Inner() {
  const params = useSearchParams();
  const router = useRouter();
  const [msg, setMsg] = useState("Connecting Google Calendar…");
  const done = useRef(false);
  useEffect(() => {
    const code = params.get("code");
    if (!code || done.current) return;
    done.current = true;
    api.googleCalendarConnect(code).then(() => router.replace("/calendar")).catch(() => setMsg("Could not connect Google Calendar. Please try again."));
  }, [params, router]);
  return <p className="p-6 text-sm">{msg}</p>;
}
export default function Callback() { return <Suspense><Inner /></Suspense>; }
