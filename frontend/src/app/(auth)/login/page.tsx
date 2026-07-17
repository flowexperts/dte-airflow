"use client";

import { useState, useTransition, use } from "react";
import { useRouter } from "next/navigation";
import { Button, Field, Input, Panel, PanelHead } from "@/components/ui";
import { login, setToken, ApiError } from "@/lib/api";

interface Props {
  searchParams: Promise<{ next?: string }>;
}

export default function LoginPage({ searchParams }: Props) {
  const { next } = use(searchParams);
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    startTransition(async () => {
      try {
        const token = await login(email, password);
        setToken(token);
        router.replace(next && next.startsWith("/") ? next : "/pipelines");
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          setError("Invalid email or password.");
        } else if (err instanceof ApiError && err.status === 403) {
          setError("Account disabled.");
        } else {
          setError(err instanceof Error ? err.message : "Login failed.");
        }
      }
    });
  }

  return (
    <div className="min-h-screen grid place-items-center bg-bg text-text p-8">
      <Panel className="w-full max-w-sm">
        <PanelHead label="Sign in" />
        <form onSubmit={onSubmit} className="p-4 flex flex-col gap-4">
          <Field label="Email">
            <Input
              type="email"
              required
              autoFocus
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
          <Field label="Password">
            <Input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          {error ? (
            <div className="text-sm text-red-500 font-mono">{error}</div>
          ) : null}
          <Button type="submit" variant="primary" disabled={pending}>
            {pending ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </Panel>
    </div>
  );
}
