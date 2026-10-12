import { Hourglass } from "lucide-react";
import { copy } from "@vtrs/core";
import { cn } from "@/lib/cn";

/**
 * Dashed outline means "not final" and is used for nothing else. Mandatory beside any leader,
 * margin or projected winner; never hidden on small screens.
 */
export function ProvisionalBadge({
  caption = false,
  className,
}: {
  caption?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex flex-col items-start gap-1", className)}>
      <span
        title={copy.provisional.caption}
        className="inline-flex h-6 items-center gap-1 whitespace-nowrap rounded-full border-[1.5px] border-dashed border-strong-foreground bg-canvas px-2 text-label font-semibold text-strong-foreground"
      >
        <Hourglass className="h-3.5 w-3.5" aria-hidden />
        {copy.provisional.label}
      </span>
      {caption ? (
        <span className="text-caption text-subtle-foreground">{copy.provisional.caption}</span>
      ) : null}
    </span>
  );
}
