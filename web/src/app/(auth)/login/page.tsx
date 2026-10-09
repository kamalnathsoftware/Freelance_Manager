"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { loginSchema, type LoginInput, ApiError } from "@fm/shared";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<LoginInput>({ resolver: zodResolver(loginSchema) });

  const onSubmit = async (v: LoginInput) => {
    setError("");
    try {
      const r = await api.login(v);
      if (r.mfa_required) setMfaToken(r.mfa_token); else router.replace("/dashboard");
    } catch (e) { setError(e instanceof ApiError ? e.message : "Something went wrong"); }
  };
  const submitCode = async (e: React.FormEvent) => {
    e.preventDefault(); setError("");
    try { await api.login2fa(mfaToken!, code); router.replace("/dashboard"); }
    catch (err) { setError(err instanceof ApiError ? err.message : "Something went wrong"); }
  };

  return (
    <Card>
      {mfaToken ? (
        <form onSubmit={submitCode} className="space-y-4">
          <h2 className="font-semibold">Two-factor authentication</h2>
          <Input label="6-digit code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <Button className="w-full" type="submit">Verify</Button>
        </form>
      ) : (
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <h2 className="font-semibold">Welcome back</h2>
          <Input label="Email" type="email" autoComplete="email" error={errors.email?.message} {...register("email")} />
          <Input label="Password" type="password" autoComplete="current-password" error={errors.password?.message} {...register("password")} />
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <Button className="w-full" type="submit" disabled={isSubmitting}>Sign in</Button>
          <div className="flex justify-between text-sm text-muted">
            <Link href="/forgot-password" className="hover:text-fg">Forgot password?</Link>
            <Link href="/signup" className="hover:text-fg">Create account</Link>
          </div>
        </form>
      )}
    </Card>
  );
}
