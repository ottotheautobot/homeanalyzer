"use client";

import { GitCompare, House, Map as MapIcon, Settings } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/tours", label: "Tours", icon: House, match: (p: string) => p === "/tours" || p.startsWith("/tours/") },
  { href: "/map", label: "Map", icon: MapIcon, match: (p: string) => p.startsWith("/map") },
  { href: "/compare", label: "Compare", icon: GitCompare, match: (p: string) => p.startsWith("/compare") },
  { href: "/settings", label: "Settings", icon: Settings, match: (p: string) => p.startsWith("/settings") },
];

/** Bottom tab bar — visible on mobile only, mimicking the native iOS
 *  app pattern. Desktop keeps the top header nav. Sticks to the bottom
 *  with safe-area padding so it clears the iPhone home indicator. */
export function MobileNav() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Primary"
      className="sm:hidden fixed inset-x-0 bottom-0 z-40 border-t border-zinc-200 dark:border-zinc-800 bg-white/95 dark:bg-zinc-950/95 backdrop-blur supports-[backdrop-filter]:bg-white/85 dark:supports-[backdrop-filter]:bg-zinc-950/85"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <ul className="grid grid-cols-4">
        {TABS.map((t) => {
          const active = t.match(pathname);
          const Icon = t.icon;
          return (
            <li key={t.href}>
              <Link
                href={t.href}
                aria-current={active ? "page" : undefined}
                className={`flex flex-col items-center justify-center gap-0.5 py-2 min-h-[56px] text-[10px] font-medium tracking-wide uppercase transition-colors active:scale-95 transition-transform ${
                  active
                    ? "text-primary"
                    : "text-zinc-500 dark:text-zinc-400"
                }`}
              >
                <Icon
                  className="size-5"
                  strokeWidth={active ? 2.5 : 2}
                  aria-hidden
                />
                <span>{t.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
