import "server-only";

import { redirect } from "next/navigation";

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
  // SSR race: layout.getUser() can succeed while getSession() returns
  // null mid-token-refresh (more often on Mobile Safari). Bouncing to
  // /login mirrors the layout's behavior; throwing here would 500 the
  // page instead.
  if (!session?.access_token) {
    redirect("/login");
  }
  return callBackend<T>(path, init, session.access_token);
}
