import type { ReactElement } from "react";
import { formatNumber } from "@vtrs/core";
import { cn } from "@/lib/cn";

const STROKE_W = 4;
const STROKE_H = 22;
const GAP = 8;
const PITCH = STROKE_W + GAP;
const GROUP_W = PITCH * 3 + STROKE_W; // four upright strokes
const GROUP_GAP = 16;
const MAX_UNITS = 60;

/**
 * Ward-level reporting progress as real tally groups: four strokes plus a slash. Reported
 * units are teal; the rest are outlines. Past 60 units it falls back to a plain bar.
 */
export function TallyMeter({
  reported,
  total,
  className,
  caption = true,
}: {
  reported: number;
  total: number;
  className?: string;
  /** Show "17 of 24 reported" under the marks. Off where the count sits beside it. */
  caption?: boolean;
}) {
  const label = `${formatNumber(reported)} of ${formatNumber(total)} reported`;
  if (total > MAX_UNITS) {
    const pct = total === 0 ? 0 : (reported / total) * 100;
    return (
      <div className={cn("flex flex-col gap-1", className)}>
        <div
          role="progressbar"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={reported}
          className="h-2 overflow-hidden rounded-full bg-track"
        >
          <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
        </div>
        {caption ? <span className="text-body-sm text-subtle-foreground">{label}</span> : null}
      </div>
    );
  }

  const groups = Math.ceil(total / 5);
  const width = groups * GROUP_W + (groups - 1) * GROUP_GAP + 8;
  const marks: ReactElement[] = [];
  for (let unit = 0; unit < total; unit++) {
    const group = Math.floor(unit / 5);
    const inGroup = unit % 5;
    const x0 = 4 + group * (GROUP_W + GROUP_GAP);
    const done = unit < reported;
    const paint = done
      ? { stroke: "rgb(var(--signal-teal-mark))", strokeWidth: STROKE_W }
      : { stroke: "rgb(var(--input))", strokeWidth: 1.5 };
    if (inGroup < 4) {
      const x = x0 + inGroup * PITCH + STROKE_W / 2;
      marks.push(
        <line key={unit} x1={x} x2={x} y1={4} y2={4 + STROKE_H} strokeLinecap="round" {...paint} />,
      );
    } else {
      // The slash runs a little past the group on both sides, 2 px longer than a stroke.
      marks.push(
        <line
          key={unit}
          x1={x0 - 3}
          y1={4 + STROKE_H - 3}
          x2={x0 + GROUP_W + 3}
          y2={4 + 3}
          strokeLinecap="round"
          {...paint}
        />,
      );
    }
  }

  return (
    <figure className={cn("flex flex-col gap-1", className)}>
      <svg
        role="img"
        aria-label={label}
        width={width}
        height={STROKE_H + 8}
        viewBox={`0 0 ${width} ${STROKE_H + 8}`}
        className="max-w-full"
      >
        {marks}
      </svg>
      {caption ? (
        <figcaption className="text-body-sm text-subtle-foreground">{label}</figcaption>
      ) : null}
    </figure>
  );
}
