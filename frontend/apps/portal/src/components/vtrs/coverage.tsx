"use client";

import {
  formatNumber,
  formatPercent,
  formatTime,
  type AreaResult,
  type TimelinePointLike,
} from "./coverage-types";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";

/** Sequential scale for coverage: ink-50 -> teal-200 -> teal-400 -> teal-600 -> teal-800. */
export function coverageStyle(pct: number, reported: number): { className: string; label: string } {
  if (reported === 0) {
    return {
      className: "border-[1.5px] border-dashed border-input bg-muted text-strong-foreground",
      label: "No results yet",
    };
  }
  if (pct < 25) return { className: "bg-teal-200 text-ink-900", label: "Under 25%" };
  if (pct < 50) return { className: "bg-teal-400 text-ink-900", label: "25 to 50%" };
  if (pct < 75) return { className: "bg-teal-600 text-white", label: "50 to 75%" };
  return { className: "bg-teal-800 text-white", label: "75% and over" };
}

export function CoverageLegend() {
  const steps = [
    coverageStyle(0, 0),
    coverageStyle(10, 1),
    coverageStyle(30, 1),
    coverageStyle(60, 1),
    coverageStyle(90, 1),
  ];
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-subtle-foreground">
      {steps.map((s) => (
        <li key={s.label} className="flex items-center gap-1.5">
          <span className={cn("inline-block h-3 w-5 rounded-sm", s.className)} aria-hidden />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

/**
 * Coverage by area as a tile grid. The data has names and counts but no boundaries, so a
 * cartogram of equal tiles reads better than an inaccurate map.
 */
export function CoverageGrid({
  rows,
  onSelect,
}: {
  rows: AreaResult[];
  onSelect?: (row: AreaResult) => void;
}) {
  const sorted = [...rows].sort((a, b) => a.area_name.localeCompare(b.area_name));
  return (
    <div className="flex flex-col gap-3">
      <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        {sorted.map((row) => {
          const style = coverageStyle(row.reported_pct, row.reported_pus);
          const body = (
            <>
              <span className="line-clamp-2 text-body-sm font-semibold leading-tight">
                {row.area_name}
              </span>
              <span className="mt-auto flex items-baseline justify-between gap-2">
                <span className="tabular-nums text-h3 font-bold">
                  {formatPercent(row.reported_pct)}
                </span>
                <span className="tabular-nums text-caption">
                  {formatNumber(row.reported_pus)}/{formatNumber(row.expected_pus)}
                </span>
              </span>
            </>
          );
          const common = cn(
            "flex min-h-[84px] flex-col gap-1 rounded-md p-3 text-left",
            style.className,
          );
          return (
            <li key={row.area_id}>
              {onSelect ? (
                <button
                  type="button"
                  onClick={() => onSelect(row)}
                  className={cn(
                    common,
                    "w-full transition-transform duration-fast hover:brightness-95",
                  )}
                  aria-label={`${row.area_name}: ${formatPercent(row.reported_pct)} reported, ${row.reported_pus} of ${row.expected_pus} polling units`}
                >
                  {body}
                </button>
              ) : (
                <div className={common}>{body}</div>
              )}
            </li>
          );
        })}
      </ul>
      <CoverageLegend />
    </div>
  );
}

const H = 220;

/** The width of an element, kept current. Falls back to a sensible size before first measure. */
function useWidth<T extends HTMLElement>(fallback = 560): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const next = Math.floor(entry?.contentRect.width ?? 0);
      if (next > 0) setWidth(next);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}
const PAD = { top: 12, right: 16, bottom: 28, left: 40 };

/** One teal line against a dashed 95% target; a table below is the text alternative. */
export function CoverageChart({
  points,
  expected,
  target = 95,
}: {
  points: TimelinePointLike[];
  expected: number;
  target?: number;
}) {
  const [holder, W] = useWidth<HTMLDivElement>();
  if (points.length === 0 || expected === 0) {
    return (
      <p className="py-10 text-center text-body text-subtle-foreground">
        The chart appears once the first results arrive.
      </p>
    );
  }
  const t0 = new Date(points[0]!.at).getTime();
  const t1 = Math.max(new Date(points[points.length - 1]!.at).getTime(), t0 + 60 * 60_000);
  const x = (t: number) => PAD.left + ((t - t0) / (t1 - t0)) * (W - PAD.left - PAD.right);
  const y = (pct: number) => PAD.top + (1 - pct / 100) * (H - PAD.top - PAD.bottom);
  const series = points.map((p) => ({
    t: new Date(p.at).getTime(),
    pct: Math.min(100, (p.cumulative / expected) * 100),
  }));
  const path = series
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(p.t).toFixed(1)},${y(p.pct).toFixed(1)}`)
    .join(" ");
  const last = series[series.length - 1]!;
  const ticks = [0, 25, 50, 75, 100];
  const summary = `${formatPercent(last.pct)} of ${formatNumber(expected)} polling units reported by ${formatTime(points[points.length - 1]!.at)}.`;

  return (
    <figure className="flex flex-col gap-2">
      <div ref={holder} className="w-full">
        <svg
          width={W}
          height={H}
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`Reporting over time. ${summary}`}
        >
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={y(tick)}
                y2={y(tick)}
                stroke="rgb(var(--border))"
                strokeWidth={1}
              />
              <text
                x={PAD.left - 8}
                y={y(tick) + 4}
                textAnchor="end"
                fontSize={12}
                fill="rgb(var(--subtle-foreground))"
                className="tabular-nums"
              >
                {tick}%
              </text>
            </g>
          ))}
          <line
            x1={PAD.left}
            x2={W - PAD.right}
            y1={y(target)}
            y2={y(target)}
            stroke="rgb(var(--input))"
            strokeWidth={1.5}
            strokeDasharray="6 4"
          />
          <text
            x={W - PAD.right}
            y={y(target) - 6}
            textAnchor="end"
            fontSize={12}
            fill="rgb(var(--subtle-foreground))"
          >
            Target {target}%
          </text>
          <path
            d={path}
            fill="none"
            stroke="rgb(var(--signal-teal-mark))"
            strokeWidth={2.5}
            strokeLinejoin="round"
          />
          <circle cx={x(last.t)} cy={y(last.pct)} r={4} fill="rgb(var(--signal-teal-mark))" />
          {[t0, (t0 + t1) / 2, t1].map((t, i) => (
            <text
              key={i}
              x={x(t)}
              y={H - 8}
              textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"}
              fontSize={12}
              fill="rgb(var(--subtle-foreground))"
              className="tabular-nums"
            >
              {formatTime(t)}
            </text>
          ))}
        </svg>
      </div>
      <figcaption className="text-body-sm text-subtle-foreground">{summary}</figcaption>
      <details className="text-body-sm">
        <summary className="cursor-pointer text-primary">Show as a table</summary>
        <table className="mt-2 w-full text-left">
          <thead>
            <tr>
              <th className="py-1 pr-4 font-semibold">Time</th>
              <th className="py-1 pr-4 text-right font-semibold">New</th>
              <th className="py-1 text-right font-semibold">Total</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.at}>
                <td className="py-0.5 pr-4 tabular-nums">{formatTime(p.at)}</td>
                <td className="py-0.5 pr-4 text-right tabular-nums">
                  {formatNumber(p.newly_reported)}
                </td>
                <td className="py-0.5 text-right tabular-nums">{formatNumber(p.cumulative)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
