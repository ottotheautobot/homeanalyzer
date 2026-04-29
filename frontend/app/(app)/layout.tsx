import { GitCompare, Home, LogOut, Map as MapIcon, Settings } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import { signOut } from "@/app/actions/auth";
import { Providers } from "@/app/providers";
import { MobileNav } from "@/components/mobile-nav";
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
        <header
          className="sticky top-0 z-30 border-b border-zinc-200 dark:border-zinc-800 bg-white/85 dark:bg-zinc-950/85 backdrop-blur supports-[backdrop-filter]:bg-white/70 dark:supports-[backdrop-filter]:bg-zinc-950/70"
          style={{ paddingTop: "env(safe-area-inset-top)" }}
        >
          <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-2.5 min-h-[52px]">
            <Link
              href="/tours"
              className="flex items-center gap-2 group active:scale-95 transition-transform"
              aria-label="HomeAnalyzer home"
            >
              <span className="inline-flex items-center justify-center size-8 rounded-lg bg-primary text-primary-foreground">
                <Home className="size-4" strokeWidth={2.5} />
              </span>
              <span
                className="font-display font-bold text-lg tracking-tight leading-none"
                style={{ fontFamily: "var(--font-display)" }}
              >
                <span className="text-zinc-900 dark:text-zinc-50">Home</span>
                <span className="text-primary">Analyzer</span>
              </span>
            </Link>
            {/* Desktop nav. Mobile uses the bottom tab bar. */}
            <nav className="hidden sm:flex items-center gap-1">
              <Link
                href="/map"
                className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-900 hover:text-zinc-900 dark:hover:text-zinc-50 transition-colors"
              >
                <MapIcon className="size-4" />
                Map
              </Link>
              <Link
                href="/compare"
                className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-900 hover:text-zinc-900 dark:hover:text-zinc-50 transition-colors"
              >
                <GitCompare className="size-4" />
                Compare
              </Link>
              <Link
                href="/settings"
                className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-900 hover:text-zinc-900 dark:hover:text-zinc-50 transition-colors"
              >
                <Settings className="size-4" />
                Settings
              </Link>
              <form action={signOut}>
                <button
                  type="submit"
                  className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-900 hover:text-zinc-900 dark:hover:text-zinc-50 transition-colors"
                  aria-label="Sign out"
                >
                  <LogOut className="size-4" />
                  Sign out
                </button>
              </form>
            </nav>
            {/* Mobile: keep just sign-out in the header — the four
                primary nav items live in the bottom tab bar. */}
            <form action={signOut} className="sm:hidden">
              <button
                type="submit"
                className="inline-flex items-center justify-center size-10 rounded-md text-zinc-600 dark:text-zinc-400 active:bg-zinc-100 dark:active:bg-zinc-900 active:scale-95 transition-all"
                aria-label="Sign out"
              >
                <LogOut className="size-5" />
              </button>
            </form>
          </div>
        </header>
        <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-5 pb-24 sm:pb-5">
          {children}
        </main>
        <MobileNav />
      </div>
    </Providers>
  );
}
