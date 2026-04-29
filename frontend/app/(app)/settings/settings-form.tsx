"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { clientFetch } from "@/lib/api-client";

type FormShape = {
  email: string;
  name: string;
  default_zoom_url: string;
};

type SaveResponse = {
  id: string;
  email: string;
  name: string | null;
  default_zoom_url: string | null;
};

export function SettingsForm({ initial }: { initial: FormShape }) {
  const [name, setName] = useState(initial.name);
  const [zoomUrl, setZoomUrl] = useState(initial.default_zoom_url);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: async (): Promise<SaveResponse> =>
      clientFetch<SaveResponse>("/me", {
        method: "PATCH",
        body: JSON.stringify({
          name: name.trim() || null,
          default_zoom_url: zoomUrl.trim() || null,
        }),
      }),
    onSuccess: () => setSavedAt(new Date().toLocaleTimeString()),
  });

  const dirty =
    name !== initial.name || zoomUrl !== initial.default_zoom_url;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!save.isPending) save.mutate();
      }}
      className="space-y-4"
    >
      <div className="space-y-1.5">
        <Label htmlFor="email">Email</Label>
        <Input id="email" value={initial.email} disabled readOnly />
        <p className="text-xs text-zinc-500">
          Tied to your login. To change, sign in with the new email.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="name">Display name</Label>
        <Input
          id="name"
          placeholder="e.g. Allen"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={200}
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="zoom">Default Zoom URL</Label>
        <Input
          id="zoom"
          placeholder="https://zoom.us/j/123456789?pwd=…"
          value={zoomUrl}
          onChange={(e) => setZoomUrl(e.target.value)}
          maxLength={2000}
          inputMode="url"
        />
        <p className="text-xs text-zinc-500">
          We&apos;ll use this when you tap &ldquo;Start tour&rdquo; so you
          don&apos;t have to paste it each time. If your meeting requires a
          passcode, copy the full link Zoom gives you (it includes
          <code className="mx-1 px-1 rounded bg-zinc-100 dark:bg-zinc-800 text-[10px]">?pwd=</code>
          at the end) — our listener can&apos;t enter passcodes manually.
        </p>
      </div>

      {save.isError ? (
        <p className="text-xs text-red-600 dark:text-red-400">
          {save.error instanceof Error ? save.error.message : "Failed to save"}
        </p>
      ) : null}

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={!dirty || save.isPending}>
          {save.isPending ? (
            <Loader2 className="size-4 mr-1.5 animate-spin" />
          ) : null}
          Save
        </Button>
        {savedAt && !save.isPending ? (
          <span className="text-xs text-emerald-600 dark:text-emerald-400">
            Saved at {savedAt}
          </span>
        ) : null}
      </div>
    </form>
  );
}
