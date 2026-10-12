import { formatNumber, formatPercent } from "@vtrs/core";
import { cn } from "@/lib/cn";
import { ProvisionalBadge } from "./provisional";

/** Series 1 (teal) is always the organisation's own candidate; others take the rest in order. */
const SERIES = ["#00907F", "#3D4FD6", "#C2408A", "#E0701A", "#7A5AC8", "#5B6B7A"];
export const seriesColor = (index: number, own: boolean): string =>
  own ? SERIES[0]! : SERIES[1 + (index % (SERIES.length - 1))]!;

export interface BarRow {
  id: string;
  name: string;
  party: string;
  votes: number;
  own?: boolean;
  leader?: boolean;
}

export function CandidateBars({ rows, className }: { rows: BarRow[]; className?: string }) {
  const total = rows.reduce((sum, r) => sum + r.votes, 0);
  const max = Math.max(1, ...rows.map((r) => r.votes));
  let other = 0;
  return (
    <ul className={cn("flex flex-col gap-4", className)}>
      {rows.map((row) => {
        const color = seriesColor(row.own ? 0 : other++, !!row.own);
        const pct = total === 0 ? 0 : (row.votes / total) * 100;
        return (
          <li key={row.id} className="flex flex-col gap-1.5">
            <div className="flex items-baseline justify-between gap-3">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <span className="truncate text-body font-semibold">{row.name}</span>
                <span className="text-body-sm text-subtle-foreground">{row.party}</span>
                {row.leader ? <ProvisionalBadge /> : null}
              </div>
              <span className="tabular-nums text-h3 font-bold">{formatNumber(row.votes)}</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="h-3 flex-1 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${(row.votes / max) * 100}%`, backgroundColor: color }}
                />
              </div>
              <span className="w-14 text-right tabular-nums text-body-sm text-subtle-foreground">
                {formatPercent(pct)}
              </span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
