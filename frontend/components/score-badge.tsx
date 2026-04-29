import { cn } from "@/lib/utils";

/** Color-coded score pill — color tracks the same thresholds as the map
 *  pins so the user builds one mental scale across the app. */
function scoreClasses(score: number): string {
  if (score >= 8) return "bg-emerald-500 text-white";
  if (score >= 6) return "bg-green-500 text-white";
  if (score >= 4) return "bg-amber-500 text-white";
  return "bg-red-500 text-white";
}

export function ScoreBadge({
  score,
  size = "default",
  className,
}: {
  score: number;
  size?: "default" | "sm" | "lg";
  className?: string;
}) {
  const sizing =
    size === "lg"
      ? "h-8 px-2.5 text-sm rounded-lg gap-1"
      : size === "sm"
        ? "h-5 px-1.5 text-[10px] rounded-md gap-0.5"
        : "h-6 px-2 text-xs rounded-md gap-1";
  return (
    <span
      className={cn(
        "inline-flex items-center font-semibold tabular-nums shadow-sm",
        sizing,
        scoreClasses(score),
        className,
      )}
    >
      <svg
        className={size === "lg" ? "size-3.5" : "size-3"}
        viewBox="0 0 24 24"
        fill="currentColor"
        aria-hidden
      >
        <path d="M12 2l2.39 7.36H22l-6.18 4.49L18.21 21 12 16.51 5.79 21l2.39-7.15L2 9.36h7.61z" />
      </svg>
      {score.toFixed(1)}
    </span>
  );
}
