import { Skeleton } from "@/components/ui/skeleton";

export default function TourDetailLoading() {
  return (
    <div className="space-y-5">
      <div>
        <Skeleton className="h-4 w-12 mb-2" />
        <Skeleton className="h-7 w-2/3 mb-1" />
        <Skeleton className="h-4 w-1/3" />
      </div>
      <div className="grid gap-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton
            key={i}
            className="h-[110px] rounded-xl"
            style={{ animationDelay: `${i * 60}ms` }}
          />
        ))}
      </div>
    </div>
  );
}
