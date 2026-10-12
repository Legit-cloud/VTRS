"use client";

import { Check } from "lucide-react";
import { cn } from "@/lib/cn";

export const STAGES = [
  { key: "DRAFT", label: "Set up", hint: "Add contests and candidates" },
  { key: "CONFIGURED", label: "Ready", hint: "Everything is in place" },
  { key: "LOCKED", label: "Locked", hint: "Setup is frozen" },
  { key: "LIVE", label: "Live", hint: "Agents are reporting" },
  { key: "CLOSED", label: "Closed", hint: "No more results" },
  { key: "RECONCILED", label: "Final", hint: "Results confirmed" },
] as const;

export const stageIndex = (status: string): number =>
  Math.max(
    0,
    STAGES.findIndex((s) => s.key === status),
  );

/** Where this election is on its way from setup to confirmed results. */
export function StageTracker({ status }: { status: string }) {
  const current = stageIndex(status);
  return (
    <ol
      aria-label="Election stages"
      className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3 lg:grid-cols-6"
    >
      {STAGES.map((stage, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li
            key={stage.key}
            aria-current={active ? "step" : undefined}
            className="flex items-start gap-3"
          >
            <span
              className={cn(
                "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 text-label font-bold tabular-nums",
                done && "border-primary bg-primary text-primary-foreground",
                active && "border-primary bg-primary-soft text-primary-soft-foreground",
                !done && !active && "border-input text-muted-foreground",
              )}
            >
              {done ? <Check className="h-4 w-4" aria-hidden /> : i + 1}
            </span>
            <span className="min-w-0">
              <span
                className={cn(
                  "block text-body-sm",
                  active ? "font-bold text-foreground" : "font-semibold text-strong-foreground",
                )}
              >
                {stage.label}
                {active ? <span className="sr-only"> (you are here)</span> : null}
              </span>
              <span className="block text-caption text-subtle-foreground">{stage.hint}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
