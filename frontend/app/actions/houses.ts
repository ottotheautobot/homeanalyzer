"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { serverFetch } from "@/lib/api-server";
import type { House } from "@/lib/types";

const houseSchema = z.object({
  address: z.string().trim().min(1, "Address is required"),
  list_price: z
    .string()
    .trim()
    .optional()
    .transform((v) => (v ? Number(v) : undefined))
    .pipe(z.number().nonnegative().optional()),
  sqft: z
    .string()
    .trim()
    .optional()
    .transform((v) => (v ? Number(v) : undefined))
    .pipe(z.number().int().nonnegative().optional()),
  beds: z
    .string()
    .trim()
    .optional()
    .transform((v) => (v ? Number(v) : undefined))
    .pipe(z.number().nonnegative().optional()),
  baths: z
    .string()
    .trim()
    .optional()
    .transform((v) => (v ? Number(v) : undefined))
    .pipe(z.number().nonnegative().optional()),
  listing_url: z
    .string()
    .trim()
    .url("Listing URL must be a valid URL")
    .optional()
    .or(z.literal("")),
  scheduled_at: z.string().trim().optional().or(z.literal("")),
});

export async function createHouse(
  tourId: string,
  _prev: { error?: string } | undefined,
  formData: FormData,
): Promise<{ error?: string; ok?: boolean }> {
  const parsed = houseSchema.safeParse({
    address: formData.get("address"),
    list_price: formData.get("list_price") ?? "",
    sqft: formData.get("sqft") ?? "",
    beds: formData.get("beds") ?? "",
    baths: formData.get("baths") ?? "",
    listing_url: formData.get("listing_url") ?? "",
    scheduled_at: formData.get("scheduled_at") ?? "",
  });
  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  }

  const payload: Record<string, unknown> = { address: parsed.data.address };
  if (parsed.data.list_price !== undefined)
    payload.list_price = parsed.data.list_price;
  if (parsed.data.sqft !== undefined) payload.sqft = parsed.data.sqft;
  if (parsed.data.beds !== undefined) payload.beds = parsed.data.beds;
  if (parsed.data.baths !== undefined) payload.baths = parsed.data.baths;
  if (parsed.data.listing_url) payload.listing_url = parsed.data.listing_url;
  if (parsed.data.scheduled_at)
    payload.scheduled_at = new Date(parsed.data.scheduled_at).toISOString();

  try {
    await serverFetch<House>(`/tours/${tourId}/houses`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    return { error: e instanceof Error ? e.message : "Failed to add house" };
  }

  revalidatePath(`/tours/${tourId}`);
  return { ok: true };
}
