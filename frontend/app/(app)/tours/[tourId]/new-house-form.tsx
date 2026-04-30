"use client";

import { useMutation } from "@tanstack/react-query";
import {
  Camera,
  Check,
  ChevronDown,
  ChevronUp,
  ImageIcon,
  Loader2,
  MapPin,
  Sparkles,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { AddressAutocomplete } from "@/components/address-autocomplete";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { clientFetch } from "@/lib/api-client";
import type { House } from "@/lib/types";

type Form = {
  address: string;
  list_price: string;
  price_kind: "sale" | "rent";
  sqft: string;
  beds: string;
  baths: string;
};

const emptyForm: Form = {
  address: "",
  list_price: "",
  price_kind: "sale",
  sqft: "",
  beds: "",
  baths: "",
};

type ParseListingOut = {
  address: string | null;
  list_price: number | null;
  price_kind: "sale" | "rent" | null;
  sqft: number | null;
  beds: number | null;
  baths: number | null;
  photo_url: string | null;
  listing_url: string;
  source:
    | "jsonld"
    | "meta"
    | "haiku"
    | "image"
    | "apify"
    | "fetch_failed"
    | "image_failed"
    | "not_configured"
    | "render_failed";
  debug_screenshot_url?: string | null;
  tier_trace?: string[] | null;
};

function buildPayload(f: Form): Record<string, unknown> {
  const out: Record<string, unknown> = {
    address: f.address.trim(),
    price_kind: f.price_kind,
  };
  const num = (s: string) => (s.trim() ? Number(s) : undefined);
  if (num(f.list_price) !== undefined) out.list_price = num(f.list_price);
  if (num(f.sqft) !== undefined) out.sqft = num(f.sqft);
  if (num(f.beds) !== undefined) out.beds = num(f.beds);
  if (num(f.baths) !== undefined) out.baths = num(f.baths);
  return out;
}

async function urlToFile(url: string): Promise<File | null> {
  // Most listing-photo CDNs (zillowstatic.com, akamai, AWS) serve
  // with permissive CORS, so a browser-direct fetch usually works.
  // If a particular host blocks CORS the catch returns null and the
  // user just picks their own photo.
  try {
    const r = await fetch(url, { mode: "cors" });
    if (!r.ok) return null;
    const blob = await r.blob();
    if (!blob.type.startsWith("image/")) return null;
    const ext = (blob.type.split("/")[1] || "jpg").split(";")[0];
    return new File([blob], `listing.${ext}`, { type: blob.type });
  } catch {
    return null;
  }
}

async function reverseGeocode(
  lat: number,
  lon: number,
): Promise<string | null> {
  try {
    const r = await fetch(
      `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${lat}&lon=${lon}&zoom=18&addressdetails=1`,
      { headers: { Accept: "application/json" } },
    );
    if (!r.ok) return null;
    const data = (await r.json()) as {
      address?: {
        house_number?: string;
        road?: string;
        city?: string;
        town?: string;
        village?: string;
        state?: string;
        postcode?: string;
      };
    };
    const a = data.address ?? {};
    const street = [a.house_number, a.road].filter(Boolean).join(" ");
    const city = a.city || a.town || a.village || "";
    const parts = [street, city, a.state, a.postcode].filter(Boolean);
    return parts.join(", ") || null;
  } catch {
    return null;
  }
}

export function NewHouseForm({ tourId }: { tourId: string }) {
  const router = useRouter();
  const [form, setForm] = useState<Form>(emptyForm);
  const [photo, setPhoto] = useState<File | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [geoStatus, setGeoStatus] = useState<string | null>(null);
  const [importNote, setImportNote] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [showFallback, setShowFallback] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const photoRef = useRef<HTMLInputElement>(null);
  const screenshotRef = useRef<HTMLInputElement>(null);
  // Track which address we already attempted auto-fill on so a quick
  // address re-selection doesn't burn another lookup credit.
  const lastTriedAddress = useRef<string | null>(null);

  function applyParsed(d: ParseListingOut): number {
    const next: Partial<Form> = {};
    let filled = 0;
    if (d.address) {
      next.address = d.address;
      filled++;
    }
    if (d.list_price != null) {
      next.list_price = String(d.list_price);
      filled++;
    }
    if (d.price_kind === "sale" || d.price_kind === "rent") {
      next.price_kind = d.price_kind;
    }
    if (d.sqft != null) {
      next.sqft = String(d.sqft);
      filled++;
    }
    if (d.beds != null) {
      next.beds = String(d.beds);
      filled++;
    }
    if (d.baths != null) {
      next.baths = String(d.baths);
      filled++;
    }
    setForm((f) => ({ ...f, ...next }));
    return filled;
  }

  // Auto-fire when the user picks an address from autocomplete. The
  // mutation runs server-side via Apify (Realtor → Zillow) and falls
  // back to Browserless+Haiku-Vision. Form fields populate inline.
  const autoFill = useMutation({
    mutationFn: async (address: string): Promise<ParseListingOut> =>
      clientFetch<ParseListingOut>("/houses/auto-fill", {
        method: "POST",
        body: JSON.stringify({ address }),
      }),
    onMutate: () => {
      setImportNote(null);
      setImportError(null);
      setShowFallback(false);
    },
    onSuccess: (d) => {
      const filled = applyParsed(d);
      if (filled === 0) {
        setImportError(
          "Couldn't find listing details. Fill in below or upload a screenshot.",
        );
        setShowFallback(true);
        setShowDetails(true);
        return;
      }
      const summaryParts = [
        d.list_price != null
          ? d.price_kind === "rent"
            ? `$${d.list_price.toLocaleString()}/mo`
            : `$${d.list_price.toLocaleString()}`
          : null,
        d.beds != null ? `${d.beds} bd` : null,
        d.baths != null ? `${d.baths} ba` : null,
        d.sqft != null ? `${d.sqft.toLocaleString()} sqft` : null,
      ].filter(Boolean);
      setImportNote(
        summaryParts.length
          ? `Imported · ${summaryParts.join(" · ")}`
          : `Imported ${filled} field${filled === 1 ? "" : "s"}.`,
      );
      // Bonus: pull the listing's exterior photo as the curb-appeal
      // shot. Backend prefers tagged-exterior entries when the actor
      // ships AI tags; falls back to first photo otherwise. Skip if
      // the user already picked their own photo.
      if (d.photo_url && !photo) {
        urlToFile(d.photo_url).then((file) => {
          if (file) {
            setPhoto((current) => current ?? file);
          }
        });
      }
    },
    onError: (e) => {
      setImportError(
        e instanceof Error
          ? "Couldn't auto-fill. Try a screenshot or fill in below."
          : "Auto-fill failed.",
      );
      setShowFallback(true);
      setShowDetails(true);
      void e;
    },
  });

  // Manual screenshot fallback for when Apify can't find the
  // property. Hidden until auto-fill has failed once.
  const importImage = useMutation({
    mutationFn: async (file: File): Promise<ParseListingOut> => {
      const fd = new FormData();
      fd.append("image", file, file.name);
      return clientFetch<ParseListingOut>(
        "/houses/parse-listing-image",
        { method: "POST", body: fd },
      );
    },
    onMutate: () => {
      setImportNote(null);
      setImportError(null);
    },
    onSuccess: (d, file) => {
      const filled = applyParsed(d);
      if (filled === 0) {
        setImportError(
          "Couldn't read that screenshot. Try a cleaner crop or fill in below.",
        );
        return;
      }
      if (!photo) setPhoto(file);
      setImportNote(
        `Imported ${filled} field${filled === 1 ? "" : "s"} from screenshot.`,
      );
    },
    onError: (e) => {
      setImportError(
        e instanceof Error ? e.message : "Couldn't read that screenshot.",
      );
    },
  });

  function handleAddressSelect(address: string) {
    setForm((f) => ({ ...f, address }));
    if (
      address.trim().length >= 8 &&
      address.trim() !== lastTriedAddress.current
    ) {
      lastTriedAddress.current = address.trim();
      autoFill.mutate(address.trim());
    }
  }

  useEffect(() => {
    if (!photo) {
      setPhotoPreview(null);
      return;
    }
    const url = URL.createObjectURL(photo);
    setPhotoPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  const create = useMutation({
    mutationFn: async (): Promise<House> => {
      const house = await clientFetch<House>(`/tours/${tourId}/houses`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildPayload(form)),
      });
      if (photo) {
        const fd = new FormData();
        fd.append("photo", photo, photo.name);
        await clientFetch<House>(`/houses/${house.id}/photo`, {
          method: "POST",
          body: fd,
        });
      }
      return house;
    },
    onSuccess: () => {
      setForm(emptyForm);
      setPhoto(null);
      setImportNote(null);
      setImportError(null);
      setShowFallback(false);
      setShowDetails(false);
      lastTriedAddress.current = null;
      if (photoRef.current) photoRef.current.value = "";
      router.refresh();
    },
  });

  function useMyLocation() {
    if (!navigator.geolocation) {
      setGeoStatus("Geolocation not supported by this browser");
      return;
    }
    setGeoStatus("Locating…");
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const addr = await reverseGeocode(
          pos.coords.latitude,
          pos.coords.longitude,
        );
        if (addr) {
          handleAddressSelect(addr);
          setGeoStatus(null);
        } else {
          setGeoStatus("Couldn't resolve an address from your location");
        }
      },
      (err) => {
        const PERMISSION_DENIED = 1;
        const POSITION_UNAVAILABLE = 2;
        const TIMEOUT = 3;
        if (err.code === PERMISSION_DENIED) {
          setGeoStatus(
            "Location permission denied. Allow location in your browser settings, or just type the address.",
          );
        } else if (err.code === POSITION_UNAVAILABLE) {
          setGeoStatus(
            "Couldn't determine your location. Try again outside, or type the address.",
          );
        } else if (err.code === TIMEOUT) {
          setGeoStatus(
            "Location lookup took too long. Try again or type the address.",
          );
        } else {
          setGeoStatus(
            "Couldn't get your location. Try typing the address instead.",
          );
        }
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    );
  }

  const looksReady =
    form.address.trim().length >= 4 &&
    !autoFill.isPending &&
    !create.isPending;

  return (
    <div className="space-y-4">
      {/* Address — the only required step. Autocomplete-pick fires
          auto-fill silently in the background; everything else is
          either auto-filled or optional. */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <Label htmlFor="address">Address</Label>
          <button
            type="button"
            onClick={useMyLocation}
            className="text-xs text-primary inline-flex items-center gap-1 active:scale-95 transition-transform"
          >
            <MapPin className="size-3.5" />
            Use my location
          </button>
        </div>
        <AddressAutocomplete
          id="address"
          value={form.address}
          onChange={(next) => setForm((f) => ({ ...f, address: next }))}
          onSelect={(s) => handleAddressSelect(s.address)}
          placeholder="123 Sea Breeze Ln, Fort Lauderdale, FL"
          required
          disabled={create.isPending}
        />
        {geoStatus ? (
          <p className="text-xs text-zinc-500">{geoStatus}</p>
        ) : null}

        {/* Auto-fill status row — sits inline under address so the
            user sees what we're doing without scrolling. */}
        {autoFill.isPending ? (
          <p className="text-xs text-zinc-500 inline-flex items-center gap-1.5 pt-0.5">
            <Loader2 className="size-3.5 animate-spin" />
            Looking up listing details…
          </p>
        ) : importNote ? (
          <p className="text-xs text-emerald-600 dark:text-emerald-400 inline-flex items-center gap-1.5 pt-0.5">
            <Check className="size-3.5" />
            {importNote}
          </p>
        ) : importError ? (
          <p className="text-xs text-amber-600 dark:text-amber-400 inline-flex items-center gap-1.5 pt-0.5">
            <X className="size-3.5" />
            {importError}
          </p>
        ) : null}
      </div>

      {/* Curb-appeal photo. Renders prominently on mobile so a
          one-handed flow is "pick address, snap photo, submit". */}
      <div className="space-y-1.5">
        <Label>
          Curb-appeal photo{" "}
          <span className="text-xs font-normal text-zinc-400">(optional)</span>
        </Label>
        <input
          ref={photoRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="hidden"
          onChange={(e) => setPhoto(e.target.files?.[0] ?? null)}
        />
        {photoPreview ? (
          <div className="flex items-center gap-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={photoPreview}
              alt=""
              className="size-20 rounded-lg object-cover border border-zinc-200 dark:border-zinc-800 shrink-0"
            />
            <div className="flex flex-col gap-1.5">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => photoRef.current?.click()}
                disabled={create.isPending}
              >
                Replace
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => {
                  setPhoto(null);
                  if (photoRef.current) photoRef.current.value = "";
                }}
                disabled={create.isPending}
              >
                Remove
              </Button>
            </div>
          </div>
        ) : (
          <Button
            type="button"
            variant="outline"
            onClick={() => photoRef.current?.click()}
            disabled={create.isPending}
            className="w-full sm:w-auto"
          >
            <Camera className="size-4 mr-1.5" />
            Take photo
          </Button>
        )}
      </div>

      {/* Screenshot fallback — only appears after auto-fill failed.
          The user can drop a manual Zillow/Redfin screenshot to fill
          the same fields via Haiku Vision. */}
      {showFallback ? (
        <div className="rounded-lg border border-amber-200 dark:border-amber-900/40 bg-amber-50/50 dark:bg-amber-950/20 p-3 space-y-2">
          <div className="flex items-start gap-2 text-xs text-amber-700 dark:text-amber-400">
            <Sparkles className="size-4 shrink-0 mt-0.5" />
            <span className="leading-snug">
              Couldn&apos;t find this listing automatically. Drop a
              screenshot from your phone and we&apos;ll read it instead.
            </span>
          </div>
          <input
            ref={screenshotRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) importImage.mutate(file);
              e.target.value = "";
            }}
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => screenshotRef.current?.click()}
            disabled={importImage.isPending}
          >
            {importImage.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <ImageIcon className="size-4" />
            )}
            <span className="ml-1.5">Upload listing screenshot</span>
          </Button>
        </div>
      ) : null}

      {/* Detail fields — collapsed by default since auto-fill usually
          handles them. User can expand to verify or override. */}
      <div className="rounded-lg border border-zinc-200 dark:border-zinc-800">
        <button
          type="button"
          onClick={() => setShowDetails((s) => !s)}
          className="w-full flex items-center justify-between gap-2 px-3 py-2.5 text-sm text-zinc-700 dark:text-zinc-300 active:bg-zinc-50 dark:active:bg-zinc-900 active:scale-[0.99] transition-all"
          aria-expanded={showDetails}
        >
          <span className="font-medium">
            {showDetails ? "Hide" : "Show"} details
          </span>
          {showDetails ? (
            <ChevronUp className="size-4 text-zinc-400" />
          ) : (
            <ChevronDown className="size-4 text-zinc-400" />
          )}
        </button>
        {showDetails ? (
          <div className="border-t border-zinc-200 dark:border-zinc-800 p-3 space-y-3">
            <div className="space-y-1.5">
              <Label>Price</Label>
              <div className="flex gap-2">
                <div className="inline-flex rounded-lg border border-zinc-200 dark:border-zinc-800 p-0.5 shrink-0">
                  {(["sale", "rent"] as const).map((k) => (
                    <button
                      key={k}
                      type="button"
                      onClick={() =>
                        setForm((f) => ({ ...f, price_kind: k }))
                      }
                      disabled={create.isPending}
                      className={`px-3 h-8 rounded-md text-xs font-medium transition-colors ${
                        form.price_kind === k
                          ? "bg-primary text-primary-foreground"
                          : "text-zinc-600 dark:text-zinc-400"
                      }`}
                    >
                      {k === "sale" ? "Sale" : "Rent"}
                    </button>
                  ))}
                </div>
                <Input
                  id="list_price"
                  inputMode="numeric"
                  placeholder={form.price_kind === "rent" ? "3500" : "850000"}
                  value={form.list_price}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, list_price: e.target.value }))
                  }
                  disabled={create.isPending}
                  className="flex-1"
                />
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div className="space-y-1.5">
                <Label htmlFor="beds" className="text-xs">
                  Beds
                </Label>
                <Input
                  id="beds"
                  inputMode="decimal"
                  placeholder="3"
                  value={form.beds}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, beds: e.target.value }))
                  }
                  disabled={create.isPending}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="baths" className="text-xs">
                  Baths
                </Label>
                <Input
                  id="baths"
                  inputMode="decimal"
                  placeholder="2.5"
                  value={form.baths}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, baths: e.target.value }))
                  }
                  disabled={create.isPending}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="sqft" className="text-xs">
                  Sqft
                </Label>
                <Input
                  id="sqft"
                  inputMode="numeric"
                  placeholder="1850"
                  value={form.sqft}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, sqft: e.target.value }))
                  }
                  disabled={create.isPending}
                />
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {create.isError ? (
        <p className="text-sm text-red-600 dark:text-red-400">
          {create.error instanceof Error ? create.error.message : "Failed"}
        </p>
      ) : null}
      <Button
        onClick={() => create.mutate()}
        disabled={!looksReady}
        className="w-full"
        size="lg"
      >
        {create.isPending ? "Adding…" : "Add house"}
      </Button>
    </div>
  );
}
