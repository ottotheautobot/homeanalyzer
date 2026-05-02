"use client";

import { Home, Mail, Share2 } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

type Tab = "houses" | "invites" | "share";

const TABS: { id: Tab; label: string; icon: typeof Home }[] = [
  { id: "houses", label: "Houses", icon: Home },
  { id: "invites", label: "Invites", icon: Mail },
  { id: "share", label: "Share", icon: Share2 },
];

export function TourTabs({
  housesTab,
  invitesTab,
  shareTab,
  inviteCount,
}: {
  housesTab: React.ReactNode;
  invitesTab: React.ReactNode;
  shareTab: React.ReactNode;
  inviteCount: number;
}) {
  const [tab, setTab] = useState<Tab>("houses");
  return (
    <div className="space-y-5">
      <div
        role="tablist"
        aria-label="Tour sections"
        className="inline-flex w-full sm:w-auto rounded-lg bg-zinc-100 dark:bg-zinc-900 p-1 text-sm"
      >
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = t.id === tab;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setTab(t.id)}
              className={cn(
                "flex-1 sm:flex-initial inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md transition-colors",
                active
                  ? "bg-white dark:bg-zinc-950 text-foreground shadow-sm"
                  : "text-zinc-600 dark:text-zinc-400 hover:text-foreground",
              )}
            >
              <Icon className="size-3.5" strokeWidth={2} />
              <span>{t.label}</span>
              {t.id === "invites" && inviteCount > 0 ? (
                <span className="text-xs text-zinc-500">({inviteCount})</span>
              ) : null}
            </button>
          );
        })}
      </div>
      <div role="tabpanel">
        {tab === "houses" ? housesTab : null}
        {tab === "invites" ? invitesTab : null}
        {tab === "share" ? shareTab : null}
      </div>
    </div>
  );
}
