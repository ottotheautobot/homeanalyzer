"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * iOS Safari and Chrome aggressively suspend background tabs — WebSocket
 * connections die and Supabase Realtime subscriptions miss events. When the
 * tab returns to foreground, immediately call router.refresh() so the page
 * re-renders with fresh server data. Existing realtime subscriptions
 * reconnect themselves once the tab is active again, so live updates resume
 * from there.
 */
export function RefreshOnVisibility() {
  const router = useRouter();
  useEffect(() => {
    function onVis() {
      if (document.visibilityState === "visible") {
        router.refresh();
      }
    }
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [router]);
  return null;
}
