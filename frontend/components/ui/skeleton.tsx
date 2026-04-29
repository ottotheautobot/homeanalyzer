import { cn } from "@/lib/utils";

/** Pulsing placeholder for content that's loading. Used by route-level
 *  loading.tsx files so SSR navigation feels instant — the user sees
 *  layout immediately and content fades in, instead of a blank page
 *  + spinner that flashes. */
export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-md bg-zinc-200 dark:bg-zinc-800",
        className,
      )}
      {...props}
    />
  );
}
