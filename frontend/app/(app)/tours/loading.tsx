import { Skeleton } from "@/components/ui/skeleton";

export default function TourListLoading() {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <Skeleton className="h-7 w-20" />
        <div className="flex items-center gap-2">
          <Skeleton className="h-9 w-24 rounded-lg" />
          <Skeleton className="h-9 w-24 rounded-lg" />
        </div>
      </div>
      <div className="grid gap-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton
            key={i}
            className="h-[88px] rounded-xl"
            style={{ animationDelay: `${i * 60}ms` }}
          />
        ))}
      </div>
    </div>
  );
}
