import { Skeleton } from "@/components/ui/skeleton";

export default function HouseLoading() {
  return (
    <div className="space-y-4">
      <div>
        <Skeleton className="h-4 w-12 mb-2" />
        <div className="mt-1 flex items-start justify-between gap-3">
          <div className="min-w-0 flex items-center gap-3 flex-1">
            <Skeleton className="size-12 rounded-md shrink-0" />
            <div className="space-y-1.5 flex-1 min-w-0">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          </div>
          <div className="shrink-0 space-y-1.5">
            <Skeleton className="h-6 w-24" />
            <Skeleton className="h-3 w-16 ml-auto" />
          </div>
        </div>
      </div>
      <Skeleton className="h-24 rounded-xl" />
      <div className="flex gap-1 border-b border-zinc-200 dark:border-zinc-800 pb-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-9 w-20 rounded-md" />
        ))}
      </div>
      <Skeleton className="h-72 rounded-xl" />
    </div>
  );
}
