"use client";

import { X } from "lucide-react";
import { useEffect } from "react";

/** Mobile: bottom sheet that slides up from the bottom (with safe-area
 *  padding so it clears the home indicator) — feels native, easier to
 *  one-thumb-tap. Desktop: centered modal as before. */
export function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    // Lock background scroll while open — otherwise iOS rubber-bands
    // through the dialog when the user taps the backdrop.
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50 sm:p-4 animate-in fade-in duration-150"
      onClick={onClose}
    >
      <div
        className="w-full sm:max-w-md bg-white dark:bg-zinc-950 border-t sm:border border-zinc-200 dark:border-zinc-800 sm:rounded-2xl rounded-t-2xl shadow-xl animate-in slide-in-from-bottom-4 sm:slide-in-from-bottom-0 sm:zoom-in-95 duration-200 max-h-[92vh] overflow-y-auto overscroll-contain"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        style={{ paddingBottom: "max(1.5rem, env(safe-area-inset-bottom))" }}
      >
        {/* Drag handle (mobile only) — visual hint that this is a
            bottom sheet, even though we don't yet support
            drag-to-dismiss. */}
        <div className="sm:hidden flex justify-center pt-2.5 pb-1">
          <span className="block h-1 w-10 rounded-full bg-zinc-300 dark:bg-zinc-700" />
        </div>
        <div className="flex items-start justify-between gap-3 px-6 pt-3 sm:pt-6 pb-4">
          <h2 className="text-lg font-semibold leading-tight">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="-mr-2 -mt-1 inline-flex items-center justify-center size-9 rounded-md text-zinc-500 active:bg-zinc-100 dark:active:bg-zinc-900 active:scale-95 transition-all"
          >
            <X className="size-5" />
          </button>
        </div>
        <div className="px-6 pb-2">{children}</div>
      </div>
    </div>
  );
}
