"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { clientFetch } from "@/lib/api-client";

export default function FinalizePage() {
  const [botId, setBotId] = useState("");
  const [result, setResult] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function run() {
    setPending(true);
    setError(null);
    setResult(null);
    try {
      const r = await clientFetch(`/debug/finalize/${botId}`, {
        method: "POST",
      });
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="max-w-2xl space-y-4">
      <h1 className="text-xl font-semibold">Force-finalize a bot</h1>
      <p className="text-sm text-zinc-500">
        Downloads the bot&apos;s audio from Meeting BaaS and runs the
        Whisper → Haiku → Sonnet pipeline against it. Use when the webhook
        didn&apos;t reach us. Bot recording expires 4h after the bot ends.
      </p>
      <div className="space-y-2">
        <Label htmlFor="bot">Bot ID</Label>
        <Input
          id="bot"
          value={botId}
          onChange={(e) => setBotId(e.target.value)}
          placeholder="e63273b0-1d08-4b6a-a734-1592ed96513f"
        />
      </div>
      <Button onClick={run} disabled={!botId || pending}>
        {pending ? "Running…" : "Run pipeline"}
      </Button>
      {error ? (
        <pre className="text-sm text-red-600 dark:text-red-400">{error}</pre>
      ) : null}
      {result ? (
        <pre className="rounded-md border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 p-4 text-xs overflow-auto">
          {JSON.stringify(result, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}
