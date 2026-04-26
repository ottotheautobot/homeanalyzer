import { serverFetch } from "@/lib/api-server";

export const dynamic = "force-dynamic";

export default async function DebugBotPage() {
  const data = await serverFetch<unknown>("/debug/bot");
  return (
    <div className="max-w-2xl space-y-4">
      <h1 className="text-xl font-semibold">Latest bot debug</h1>
      <pre className="rounded-md border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 p-4 text-xs overflow-auto">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  );
}
