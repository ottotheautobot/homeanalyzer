import Link from "next/link";
import { redirect } from "next/navigation";

import { signOut } from "@/app/actions/auth";
import { Providers } from "@/app/providers";
import { Button } from "@/components/ui/button";
import { createSupabaseServerClient } from "@/lib/supabase/server";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  return (
    <Providers>
      <div className="flex min-h-screen flex-col">
        <header className="border-b border-zinc-200 dark:border-zinc-800 bg-white/70 dark:bg-zinc-950/70 backdrop-blur">
          <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
            <div className="flex items-center gap-4">
              <Link
                href="/tours"
                className="font-semibold tracking-tight text-zinc-900 dark:text-zinc-50"
              >
                House Tour Notes
              </Link>
              <Link
                href="/compare"
                className="text-sm text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-50"
              >
                Compare
              </Link>
            </div>
            <div className="flex items-center gap-3 text-sm">
              <span className="hidden sm:inline text-zinc-600 dark:text-zinc-400">
                {user.email}
              </span>
              <form action={signOut}>
                <Button type="submit" size="sm" variant="outline">
                  Sign out
                </Button>
              </form>
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
          {children}
        </main>
      </div>
    </Providers>
  );
}
