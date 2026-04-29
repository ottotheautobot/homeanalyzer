"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createSupabaseBrowserClient } from "@/lib/supabase/browser";

type Status =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "sent" }
  | { kind: "error"; message: string };

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!email) return;

    setStatus({ kind: "sending" });
    const supabase = createSupabaseBrowserClient();
    const redirectTo = `${window.location.origin}/auth/callback`;

    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: redirectTo },
    });

    if (error) {
      setStatus({ kind: "error", message: error.message });
    } else {
      setStatus({ kind: "sent" });
    }
  }

  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Sign in</CardTitle>
          <CardDescription>
            We&apos;ll email you a magic link.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {status.kind === "sent" ? (
            <div className="space-y-3">
              <p className="text-sm text-zinc-600 dark:text-zinc-400">
                Check <span className="font-medium">{email}</span> for a
                sign-in link. Clicking it will sign you in even if you close
                this tab.
              </p>
              <Button
                type="button"
                variant="outline"
                className="w-full"
                onClick={() => setStatus({ kind: "idle" })}
              >
                Use a different email
              </Button>
            </div>
          ) : (
            <form onSubmit={onSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  required
                  autoFocus
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  disabled={status.kind === "sending"}
                />
              </div>
              <Button
                type="submit"
                className="w-full"
                disabled={status.kind === "sending"}
              >
                {status.kind === "sending" ? "Sending…" : "Send magic link"}
              </Button>
              {status.kind === "error" && (
                <p className="text-sm text-red-600 dark:text-red-400">
                  {status.message}
                </p>
              )}
            </form>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
