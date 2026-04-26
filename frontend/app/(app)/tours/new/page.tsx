import Link from "next/link";

import { serverFetch } from "@/lib/api-server";
import type { Me } from "@/lib/types";

import { NewTourForm } from "./new-tour-form";

export default async function NewTourPage() {
  const me = await serverFetch<Me>("/me");

  return (
    <div className="max-w-lg space-y-6">
      <div>
        <Link
          href="/tours"
          className="text-sm text-zinc-600 dark:text-zinc-400 hover:underline"
        >
          ← All tours
        </Link>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">
          New tour
        </h1>
      </div>
      <NewTourForm defaultZoomUrl={me.default_zoom_url} />
    </div>
  );
}
