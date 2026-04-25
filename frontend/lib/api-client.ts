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
  return callBackend<T>(path, init, session?.access_token ?? null);
}
