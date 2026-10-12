import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/** Value in `numeral`, label below. At most one tile per row is emphasised (coverage). */
export function StatTile({
  value,
  label,
  detail,
  emphasized,
  progress,
  badge,
  className,
}: {
  value: ReactNode;
  label: string;
  detail?: ReactNode;
  emphasized?: boolean;
  /** 0 to 100 */
  progress?: number;
  badge?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex min-w-0 flex-col gap-1 rounded-lg border p-5",
        emphasized
          ? "border-transparent bg-teal-950 text-white"
          : "border-border bg-card text-card-foreground shadow-card",
        className,
      )}
    >
      <div className="tabular-nums text-numeral font-extrabold">{value}</div>
      <div className={cn("text-body-sm", emphasized ? "text-teal-100" : "text-subtle-foreground")}>
        {label}
      </div>
      {detail ? (
        <div
          className={cn("text-body-sm", emphasized ? "text-teal-100" : "text-strong-foreground")}
        >
          {detail}
        </div>
      ) : null}
      {progress !== undefined ? (
        <div className="mt-2 flex items-center gap-3">
          <div
            role="progressbar"
            aria-label={label}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progress)}
            className={cn(
              "h-2 flex-1 overflow-hidden rounded-full",
              emphasized ? "bg-teal-800" : "bg-track",
            )}
          >
            <div
              className={cn("h-full rounded-full", emphasized ? "bg-glow" : "bg-primary")}
              style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
            />
          </div>
        </div>
      ) : null}
      {badge ? <div className="mt-2">{badge}</div> : null}
    </div>
  );
}
