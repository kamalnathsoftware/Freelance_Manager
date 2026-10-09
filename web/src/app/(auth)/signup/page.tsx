"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { ApiError, signupSchema, type SignupInput } from "@fm/shared";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

export default function SignupPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<SignupInput>({ resolver: zodResolver(signupSchema) });
  const onSubmit = async (v: SignupInput) => {
    setError("");
    try { await api.signup(v); router.replace("/dashboard"); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Something went wrong"); }
  };
  return (
    <Card>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <h2 className="font-semibold">Create your account</h2>
        <Input label="Full name" autoComplete="name" error={errors.full_name?.message} {...register("full_name")} />
        <Input label="Email" type="email" autoComplete="email" error={errors.email?.message} {...register("email")} />
        <Input label="Password" type="password" autoComplete="new-password" error={errors.password?.message} {...register("password")} />
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <Button className="w-full" type="submit" disabled={isSubmitting}>Sign up</Button>
        <p className="text-center text-sm text-muted">Have an account? <Link href="/login" className="text-brand underline">Sign in</Link></p>
      </form>
    </Card>
  );
}
