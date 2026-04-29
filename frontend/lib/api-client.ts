import { createSupabaseBrowserClient } from "@/lib/supabase/browser";

import { callBackend } from "./api";

export async function clientFetch<T = unknown>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const supabase = createSupabaseBrowserClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  // Mirror the server-side serverFetch behavior (api-server.ts) — if
  // we have no session, bounce to /login instead of letting the request
  // fail with a useless "Not authenticated" 401. This trips most often
  // on Mobile Safari mid-token-refresh.
  if (!session?.access_token) {
    if (typeof window !== "undefined") {
      window.location.assign("/login");
    }
    // Even if we can't navigate (SSR edge case), still throw so the
    // caller's mutation/query surfaces the error rather than hanging.
    throw new Error("Not authenticated");
  }
  return callBackend<T>(path, init, session.access_token);
}
