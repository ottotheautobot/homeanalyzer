import { serverFetch } from "@/lib/api-server";

type DebugResult = {
  masked: {
    key_loaded: boolean;
    key_length: number;
    key_prefix: string;
    key_suffix: string;
  };
  ping_status?: number;
  ping_body?: string;
  ping_error?: string;
  ping?: string;
};

export const dynamic = "force-dynamic";

export default async function DebugMeetingbaasPage() {
  const data = await serverFetch<DebugResult>("/debug/meetingbaas");
  return (
    <div className="max-w-2xl space-y-4">
      <h1 className="text-xl font-semibold">Meeting BaaS debug</h1>
      <pre className="rounded-md border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 p-4 text-xs overflow-auto">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  );
}
