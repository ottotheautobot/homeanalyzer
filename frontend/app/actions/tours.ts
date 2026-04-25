"use server";

import { redirect } from "next/navigation";
import { z } from "zod";

import { serverFetch } from "@/lib/api-server";
import type { Tour } from "@/lib/types";

const tourSchema = z.object({
  name: z.string().trim().min(1, "Name is required"),
  location: z.string().trim().optional().or(z.literal("")),
  zoom_pmr_url: z
    .string()
    .trim()
    .url("Zoom PMR URL must be a valid URL")
    .optional()
    .or(z.literal("")),
});

export async function createTour(
  _prev: { error?: string } | undefined,
  formData: FormData,
): Promise<{ error?: string }> {
  const parsed = tourSchema.safeParse({
    name: formData.get("name"),
    location: formData.get("location"),
    zoom_pmr_url: formData.get("zoom_pmr_url"),
  });
  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message ?? "Invalid input" };
  }

  const payload = {
    name: parsed.data.name,
    location: parsed.data.location || null,
    zoom_pmr_url: parsed.data.zoom_pmr_url || null,
  };

  let tour: Tour;
  try {
    tour = await serverFetch<Tour>("/tours", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    return { error: e instanceof Error ? e.message : "Failed to create tour" };
  }

  redirect(`/tours/${tour.id}`);
}
