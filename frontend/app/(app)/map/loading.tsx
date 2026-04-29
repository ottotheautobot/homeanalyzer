import { Skeleton } from "@/components/ui/skeleton";

export default function MapLoading() {
  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1.5 flex-1 min-w-0">
          <Skeleton className="h-7 w-16" />
          <Skeleton className="h-4 w-2/3" />
        </div>
        <Skeleton className="h-9 w-28 rounded-lg shrink-0" />
      </div>
      <Skeleton className="h-[480px] rounded-xl" />
    </div>
  );
}
