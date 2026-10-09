"use client";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  return (
    <Card>
      {sent ? (
        <p className="text-sm">If an account exists for {email}, a reset link is on its way.</p>
      ) : (
        <form className="space-y-4" onSubmit={async (e) => { e.preventDefault(); await api.forgotPassword(email); setSent(true); }}>
          <h2 className="font-semibold">Reset your password</h2>
          <Input label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <Button className="w-full" type="submit">Send reset link</Button>
        </form>
      )}
      <p className="mt-4 text-center text-sm"><Link href="/login" className="text-brand">Back to sign in</Link></p>
    </Card>
  );
}
