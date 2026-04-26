"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { createSupabaseBrowserClient } from "@/lib/supabase/browser";

export function LiveRefresh({
  channel,
  table,
  filter,
}: {
  channel: string;
  table: string;
  filter: string;
}) {
  const router = useRouter();

  useEffect(() => {
    const supabase = createSupabaseBrowserClient();
    const sub = supabase
      .channel(channel)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table, filter },
        () => router.refresh(),
      )
      .subscribe();

    return () => {
      supabase.removeChannel(sub);
    };
  }, [channel, table, filter, router]);

  return null;
}
