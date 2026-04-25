import "server-only";

import { createSupabaseServerClient } from "@/lib/supabase/server";

import { callBackend } from "./api";

export async function serverFetch<T = unknown>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const supabase = await createSupabaseServerClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return callBackend<T>(path, init, session?.access_token ?? null);
}
