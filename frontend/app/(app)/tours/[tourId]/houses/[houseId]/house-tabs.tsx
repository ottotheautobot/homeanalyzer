"use client";

import { useEffect, useRef, useState } from "react";

export type TabSpec = {
  id: string;
  label: string;
  badge?: string | number;
};

/** Sticky tab strip + panels for the house page. The page renders all
 *  panel children up-front (server-side data is already loaded); this
 *  component just shows/hides them. URL hash persistence so deep links
 *  and back-button navigation land on the right tab.
 *
 *  Active tab gets a sliding underline. Strip is horizontally scrollable
 *  on tight viewports so 4-5 tabs don't get cramped. */
export function HouseTabs({
  tabs,
  defaultId,
  children,
}: {
  tabs: TabSpec[];
  defaultId: string;
  children: Record<string, React.ReactNode>;
}) {
  const [active, setActive] = useState<string>(() => {
    if (typeof window === "undefined") return defaultId;
    const hash = window.location.hash.replace("#", "");
    if (hash && tabs.some((t) => t.id === hash)) return hash;
    return defaultId;
  });
  const stripRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onHashChange() {
      const hash = window.location.hash.replace("#", "");
      if (hash && tabs.some((t) => t.id === hash)) setActive(hash);
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [tabs]);

  // Keep the active tab visible inside the horizontal scroller.
  useEffect(() => {
    const el = stripRef.current?.querySelector<HTMLElement>(
      `[data-tab-id="${active}"]`,
    );
    el?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
  }, [active]);

  function pickTab(id: string) {
    setActive(id);
    if (typeof window !== "undefined") {
      // Use replaceState to avoid pushing a new history entry per tab
      // tap — back button should leave the house page, not cycle tabs.
      window.history.replaceState(null, "", `#${id}`);
    }
  }

  return (
    <div>
      <div
        ref={stripRef}
        role="tablist"
        className="sticky top-[52px] z-20 -mx-4 px-4 mb-4 flex gap-1 overflow-x-auto overscroll-x-contain border-b border-zinc-200 dark:border-zinc-800 bg-white/95 dark:bg-zinc-950/95 backdrop-blur supports-[backdrop-filter]:bg-white/85 dark:supports-[backdrop-filter]:bg-zinc-950/85"
      >
        {tabs.map((t) => {
          const isActive = t.id === active;
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={isActive}
              aria-controls={`panel-${t.id}`}
              data-tab-id={t.id}
              onClick={() => pickTab(t.id)}
              className={`relative shrink-0 px-3 min-h-[44px] inline-flex items-center gap-1.5 text-sm font-medium transition-colors active:scale-95 ${
                isActive
                  ? "text-primary"
                  : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-50"
              }`}
            >
              <span>{t.label}</span>
              {t.badge != null ? (
                <span
                  className={`inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-semibold ${
                    isActive
                      ? "bg-primary/15 text-primary"
                      : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400"
                  }`}
                >
                  {t.badge}
                </span>
              ) : null}
              {isActive ? (
                <span
                  aria-hidden
                  className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-primary"
                />
              ) : null}
            </button>
          );
        })}
      </div>
      {tabs.map((t) => (
        <div
          key={t.id}
          role="tabpanel"
          id={`panel-${t.id}`}
          hidden={t.id !== active}
        >
          {children[t.id]}
        </div>
      ))}
    </div>
  );
}
