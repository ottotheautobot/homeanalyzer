"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Input } from "@/components/ui/input";
import { clientFetch } from "@/lib/api-client";

/** A single resolved address suggestion. The display string is what the
 *  user sees and what gets persisted; lat/lng come along so callers can
 *  skip a separate geocode round-trip. */
export type AddressSuggestion = {
  address: string;
  lat: number;
  lng: number;
};

const DEBOUNCE_MS = 300;
const MIN_QUERY_LEN = 3;

export function AddressAutocomplete({
  value,
  onChange,
  onSelect,
  placeholder,
  disabled,
  id,
  required,
  inputMode,
  maxLength,
}: {
  value: string;
  onChange: (next: string) => void;
  onSelect: (suggestion: AddressSuggestion) => void;
  placeholder?: string;
  disabled?: boolean;
  id?: string;
  required?: boolean;
  inputMode?: React.HTMLAttributes<HTMLInputElement>["inputMode"];
  maxLength?: number;
}) {
  const [suggestions, setSuggestions] = useState<AddressSuggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState<number>(-1);
  /** True once we've completed at least one query for the current text.
   *  Lets us distinguish "not queried yet" from "queried, found nothing"
   *  so we can show a helpful hint in the empty case. */
  const [hasQueried, setHasQueried] = useState(false);
  /** "down" by default; flips to "up" when there isn't enough room
   *  below the input for the dropdown (e.g. on a phone where the
   *  field is near the bottom of the visible viewport). */
  const [direction, setDirection] = useState<"up" | "down">("down");
  /** Max height of the dropdown panel, computed from available space
   *  in the chosen direction so it never overflows the viewport. */
  const [maxHeight, setMaxHeight] = useState<number>(288);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Suppress the next debounced fetch (and current dropdown open) for
  // one cycle — used after a selection so picking a result doesn't
  // immediately re-query and reopen the dropdown.
  const skipNextRef = useRef(false);

  // Click outside closes the dropdown. iOS-friendly via touchstart.
  useEffect(() => {
    function onDocPointer(e: Event) {
      const target = e.target as Node | null;
      if (containerRef.current && target && !containerRef.current.contains(target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocPointer);
    document.addEventListener("touchstart", onDocPointer);
    return () => {
      document.removeEventListener("mousedown", onDocPointer);
      document.removeEventListener("touchstart", onDocPointer);
    };
  }, []);

  // Pick "open above" vs "open below" based on available viewport
  // room. Recomputed when the dropdown opens, when its content height
  // changes (suggestions arrive), and on resize. Without this, on a
  // phone with the field near the bottom of the screen, the dropdown
  // is cropped or hidden behind the keyboard.
  useEffect(() => {
    if (!open) return;
    function reposition() {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const vh =
        typeof window !== "undefined" ? window.innerHeight : 800;
      const PAD = 12;
      const spaceBelow = vh - rect.bottom - PAD;
      const spaceAbove = rect.top - PAD;
      // Prefer below when there's >=200px (covers ~5 items). Flip up
      // when below is cramped AND above has more room.
      if (spaceBelow >= 200 || spaceBelow >= spaceAbove) {
        setDirection("down");
        setMaxHeight(Math.max(120, Math.min(320, spaceBelow)));
      } else {
        setDirection("up");
        setMaxHeight(Math.max(120, Math.min(320, spaceAbove)));
      }
    }
    reposition();
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    return () => {
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
    };
  }, [open, suggestions.length, hasQueried]);

  // Debounced fetch on value change.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (skipNextRef.current) {
      skipNextRef.current = false;
      return;
    }
    const q = value.trim();
    if (q.length < MIN_QUERY_LEN) {
      setSuggestions([]);
      setLoading(false);
      setHasQueried(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      // Cancel any in-flight previous query so a slow earlier response
      // can't clobber a faster later one.
      if (abortRef.current) abortRef.current.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setLoading(true);
      try {
        // Backend proxy: ORS Pelias preferred (much better US
        // residential coverage), Photon fallback. Single endpoint
        // regardless of provider chain.
        const data = await clientFetch<AddressSuggestion[]>(
          `/geocode/autocomplete?q=${encodeURIComponent(q)}`,
          { signal: controller.signal },
        );
        setSuggestions(data);
        // Open the dropdown either to show suggestions OR to show the
        // "didn't find a match — type the full address and submit"
        // hint. Either way we want to communicate state to the user.
        setOpen(true);
        setActive(-1);
        setHasQueried(true);
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          // Quietly drop other errors — autocomplete failure shouldn't
          // surface a UI error; user can still type a free-form address.
          setSuggestions([]);
          setHasQueried(true);
        }
      } finally {
        setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [value]);

  function pick(idx: number) {
    const s = suggestions[idx];
    if (!s) return;
    skipNextRef.current = true;
    onChange(s.address);
    onSelect(s);
    setOpen(false);
    setSuggestions([]);
    setActive(-1);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || suggestions.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(suggestions.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      pick(active);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <Input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => suggestions.length > 0 && setOpen(true)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        disabled={disabled}
        required={required}
        inputMode={inputMode}
        maxLength={maxLength}
        autoComplete="off"
        // Some mobile keyboards still autocomplete street_address despite
        // off; explicit off plus name attribute helps.
        name="address-autocomplete-do-not-autofill"
        spellCheck={false}
      />
      {loading ? (
        <Loader2 className="absolute right-2.5 top-1/2 -translate-y-1/2 size-4 animate-spin text-zinc-400" />
      ) : null}
      {open && suggestions.length > 0 ? (
        <ul
          className={`absolute z-20 left-0 right-0 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 shadow-lg overflow-y-auto overscroll-contain ${
            direction === "down" ? "top-full mt-1" : "bottom-full mb-1"
          }`}
          style={{ maxHeight }}
        >
          {suggestions.map((s, i) => {
            const isActive = i === active;
            return (
              <li key={`${s.address}-${i}`}>
                <button
                  type="button"
                  // onMouseDown(preventDefault) keeps the input from
                  // blurring (which would close the dropdown). The
                  // actual selection fires on click — iOS Safari only
                  // synthesizes click after a tap that ENDS at roughly
                  // the same spot it started, so a scroll gesture
                  // inside the list won't accidentally pick.
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={(e) => {
                    e.preventDefault();
                    pick(i);
                  }}
                  onMouseEnter={() => setActive(i)}
                  className={`w-full text-left px-3 py-2 text-sm leading-snug transition-colors ${
                    isActive
                      ? "bg-zinc-100 dark:bg-zinc-900"
                      : "hover:bg-zinc-50 dark:hover:bg-zinc-900/50"
                  }`}
                >
                  {s.address}
                </button>
              </li>
            );
          })}
        </ul>
      ) : open && hasQueried && !loading && suggestions.length === 0 ? (
        <div
          className={`absolute z-20 left-0 right-0 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 shadow-lg px-3 py-2 text-xs text-zinc-500 leading-snug ${
            direction === "down" ? "top-full mt-1" : "bottom-full mb-1"
          }`}
        >
          No matches in our address index. Type the full address and tap{" "}
          <span className="font-medium">save / add</span> anyway — we&apos;ll
          try to look it up another way.
        </div>
      ) : null}
    </div>
  );
}
