import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface TimelineItem {
  id: string;
  title: string;
  meta: string;
  /** System events are filled; human actions are outlined. */
  system?: boolean;
  detail?: ReactNode;
}

/** Append-only history: no edit or delete affordances. */
export function Timeline({ items }: { items: TimelineItem[] }) {
  return (
    <ol className="relative ml-1.5 flex flex-col gap-5 border-l-2 border-divider pl-6">
      {items.map((item) => (
        <li key={item.id} className="relative">
          <span
            aria-hidden
            className={cn(
              "absolute -left-[31px] top-1 h-3 w-3 rounded-full border-2",
              item.system ? "border-primary bg-primary" : "border-strong-foreground bg-background",
            )}
          />
          <p className="text-body font-semibold">{item.title}</p>
          <p className="text-caption text-subtle-foreground">{item.meta}</p>
          {item.detail ? (
            <div className="mt-1 text-body-sm text-strong-foreground">{item.detail}</div>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
