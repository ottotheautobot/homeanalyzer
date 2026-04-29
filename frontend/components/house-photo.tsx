import { Home } from "lucide-react";

import { cn } from "@/lib/utils";

/** House photo with a graceful placeholder. The placeholder is a soft
 *  gradient block with a Home icon — looks intentional rather than
 *  "missing data." Used in list rows, headers, anywhere a house needs
 *  a visual anchor. */
export function HousePhoto({
  src,
  alt = "",
  className,
  rounded = "rounded-xl",
}: {
  src: string | null | undefined;
  alt?: string;
  className?: string;
  rounded?: string;
}) {
  if (src) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        alt={alt}
        className={cn(
          "object-cover bg-zinc-100 dark:bg-zinc-900",
          rounded,
          className,
        )}
      />
    );
  }
  return (
    <div
      className={cn(
        "flex items-center justify-center bg-gradient-to-br from-zinc-100 to-zinc-200 dark:from-zinc-900 dark:to-zinc-800 text-zinc-400 dark:text-zinc-600",
        rounded,
        className,
      )}
      aria-hidden
    >
      <Home className="size-1/3" strokeWidth={1.5} />
    </div>
  );
}
