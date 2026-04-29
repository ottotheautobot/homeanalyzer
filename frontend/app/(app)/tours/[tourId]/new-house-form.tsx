"use client";

import { useMutation } from "@tanstack/react-query";
import { Camera, MapPin, Search } from "lucide-react";
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
  const photoRef = useRef<HTMLInputElement>(null);

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
          setForm((f) => ({ ...f, address: addr }));
          setGeoStatus(null);
        } else {
          setGeoStatus("Couldn't resolve an address from your location");
        }
      },
      (err) => {
        // Map the GeolocationPositionError codes to plain English so a
        // fresh user doesn't see "User denied Geolocation" jargon.
        const PERMISSION_DENIED = 1;
        const POSITION_UNAVAILABLE = 2;
        const TIMEOUT = 3;
        if (err.code === PERMISSION_DENIED) {
          setGeoStatus(
            "Location permission denied. Allow location access in your browser settings, or just type the address.",
          );
        } else if (err.code === POSITION_UNAVAILABLE) {
          setGeoStatus(
            "Couldn't determine your location. Try again outside, or type the address.",
          );
        } else if (err.code === TIMEOUT) {
          setGeoStatus("Location lookup took too long. Try again or type the address.");
        } else {
          setGeoStatus("Couldn't get your location. Try typing the address instead.");
        }
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    );
  }

  function searchUrl(site: "zillow" | "redfin" | "google"): string {
    const q = encodeURIComponent(form.address);
    if (site === "zillow") return `https://www.zillow.com/homes/${q}_rb/`;
    if (site === "redfin") return `https://www.redfin.com/stingray/do/location-autocomplete?location=${q}`;
    return `https://www.google.com/search?q=${q}+for+sale`;
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="space-y-1.5 sm:col-span-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="address">Address</Label>
            <button
              type="button"
              onClick={useMyLocation}
              className="text-xs text-primary inline-flex items-center gap-1 hover:underline"
            >
              <MapPin className="size-3.5" />
              Use my location
            </button>
          </div>
          <AddressAutocomplete
            id="address"
            value={form.address}
            onChange={(next) =>
              setForm((f) => ({ ...f, address: next }))
            }
            onSelect={(s) => {
              // The picked address replaces any free-text input. We
              // don't yet capture coords client-side for new-house —
              // backend lazy-geocodes when the map loads. Future:
              // pass lat/lng through so we skip the lazy step.
              setForm((f) => ({ ...f, address: s.address }));
            }}
            placeholder="123 Sea Breeze Ln, Fort Lauderdale, FL"
            required
            disabled={create.isPending}
          />
          {geoStatus ? (
            <p className="text-xs text-zinc-500">{geoStatus}</p>
          ) : null}
          {/* Always-rendered search row so it doesn't flicker in/out as
              the user types. Links activate once the address is long
              enough to plausibly match a listing. */}
          {(() => {
            const enabled = form.address.trim().length > 5;
            const linkCls = enabled
              ? "text-primary hover:underline"
              : "text-zinc-400 dark:text-zinc-600 pointer-events-none";
            return (
              <div className="flex items-center gap-3 text-xs">
                <span className="text-zinc-500 inline-flex items-center gap-1">
                  <Search className="size-3" />
                  Search listings:
                </span>
                <a
                  href={enabled ? searchUrl("zillow") : "#"}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={linkCls}
                  aria-disabled={!enabled}
                  tabIndex={enabled ? 0 : -1}
                >
                  Zillow
                </a>
                <a
                  href={enabled ? searchUrl("redfin") : "#"}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={linkCls}
                  aria-disabled={!enabled}
                  tabIndex={enabled ? 0 : -1}
                >
                  Redfin
                </a>
                <a
                  href={enabled ? searchUrl("google") : "#"}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={linkCls}
                  aria-disabled={!enabled}
                  tabIndex={enabled ? 0 : -1}
                >
                  Google
                </a>
              </div>
            );
          })()}
        </div>

        <div className="space-y-1.5 sm:col-span-2">
          <Label>Curb appeal photo</Label>
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
                className="size-20 rounded-lg object-cover border border-zinc-200 dark:border-zinc-800"
              />
              <div className="flex flex-col gap-1">
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
              size="sm"
              onClick={() => photoRef.current?.click()}
              disabled={create.isPending}
            >
              <Camera className="size-4 mr-1.5" />
              Take photo
            </Button>
          )}
        </div>

        <div className="space-y-1.5 sm:col-span-2">
          <Label>Price</Label>
          <div className="flex gap-2">
            <div className="inline-flex rounded-lg border border-zinc-200 dark:border-zinc-800 p-0.5 shrink-0">
              {(["sale", "rent"] as const).map((k) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => setForm((f) => ({ ...f, price_kind: k }))}
                  disabled={create.isPending}
                  className={`px-2.5 h-7 rounded-md text-xs font-medium transition-colors ${
                    form.price_kind === k
                      ? "bg-primary text-primary-foreground"
                      : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-50"
                  }`}
                >
                  {k === "sale" ? "Sale" : "Rent"}
                </button>
              ))}
            </div>
            <Input
              id="list_price"
              inputMode="numeric"
              placeholder={form.price_kind === "rent" ? "3500/mo" : "850000"}
              value={form.list_price}
              onChange={(e) =>
                setForm((f) => ({ ...f, list_price: e.target.value }))
              }
              disabled={create.isPending}
              className="flex-1"
            />
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="sqft">Sqft</Label>
          <Input
            id="sqft"
            inputMode="numeric"
            placeholder="1850"
            value={form.sqft}
            onChange={(e) => setForm((f) => ({ ...f, sqft: e.target.value }))}
            disabled={create.isPending}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="beds">Beds</Label>
          <Input
            id="beds"
            inputMode="decimal"
            placeholder="3"
            value={form.beds}
            onChange={(e) => setForm((f) => ({ ...f, beds: e.target.value }))}
            disabled={create.isPending}
          />
        </div>
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="baths">Baths</Label>
          <Input
            id="baths"
            inputMode="decimal"
            placeholder="2.5"
            value={form.baths}
            onChange={(e) => setForm((f) => ({ ...f, baths: e.target.value }))}
            disabled={create.isPending}
          />
        </div>
      </div>
      {create.isError ? (
        <p className="text-sm text-red-600 dark:text-red-400">
          {create.error instanceof Error ? create.error.message : "Failed"}
        </p>
      ) : null}
      <Button
        onClick={() => create.mutate()}
        disabled={!form.address.trim() || create.isPending}
        className="w-full"
        size="lg"
      >
        {create.isPending ? "Adding…" : "Add house"}
      </Button>
    </div>
  );
}
