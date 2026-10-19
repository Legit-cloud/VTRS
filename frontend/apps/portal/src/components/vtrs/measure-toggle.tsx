"use client";

import type { Measure } from "@vtrs/core";
import { cn } from "@/lib/cn";

const LABEL: Record<Measure, string> = { reported: "All results", verified: "Verified only" };

/** All results (reported) or only those a coordinator has verified against the sheet. */
export function MeasureToggle({
  value,
  onChange,
}: {
  value: Measure | undefined;
  onChange: (measure: Measure) => void;
}) {
  return (
    <div role="group" aria-label="Count" className="inline-flex rounded-md border border-border p-0.5">
      {(["reported", "verified"] as const).map((m) => (
        <button
          key={m}
          type="button"
          onClick={() => onChange(m)}
          aria-pressed={value === m}
          className={cn(
            "h-7 rounded-sm px-3 text-label font-semibold",
            value === m ? "bg-primary text-primary-foreground" : "text-strong-foreground hover:bg-muted",
          )}
        >
          {LABEL[m]}
        </button>
      ))}
    </div>
  );
}
