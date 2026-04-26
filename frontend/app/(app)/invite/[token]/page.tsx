import Link from "next/link";
import { redirect } from "next/navigation";

import { serverFetch } from "@/lib/api-server";

export const dynamic = "force-dynamic";

export default async function AcceptInvitePage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  try {
    const result = await serverFetch<{ tour_id: string }>(
      `/invites/${token}/accept`,
      { method: "POST" },
    );
    redirect(`/tours/${result.tour_id}`);
  } catch (e) {
    if (
      e &&
      typeof e === "object" &&
      "digest" in e &&
      typeof (e as { digest?: string }).digest === "string" &&
      (e as { digest: string }).digest.startsWith("NEXT_REDIRECT")
    ) {
      throw e;
    }
    return (
      <div className="max-w-md space-y-3">
        <h1 className="text-xl font-semibold">Couldn&apos;t accept invite</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {e instanceof Error ? e.message : "Unknown error"}
        </p>
        <p className="text-sm">
          Make sure you&apos;re logged in with the same email the invite was
          sent to.
        </p>
        <Link
          href="/tours"
          className="text-sm text-zinc-900 dark:text-zinc-50 underline"
        >
          Back to your tours →
        </Link>
      </div>
    );
  }
}
