import { copy, formatTime } from "@vtrs/core";
import { WifiOff } from "lucide-react";
import type { LiveState } from "@/lib/live";
import { cn } from "@/lib/cn";

/** A 6 px pulsing dot while the socket is up; a banner-worthy state when it is not. */
export function LiveIndicator({ state, asOf }: { state: LiveState; asOf?: number | null }) {
  if (state === "live") {
    return (
      <span className="inline-flex items-center gap-2 text-label font-semibold text-signal-teal-text">
        <span className="live-dot h-1.5 w-1.5 rounded-full bg-signal-teal-mark" aria-hidden />
        {copy.live.live}
        {asOf ? (
          <span className="font-medium text-subtle-foreground tabular-nums">
            · {formatTime(asOf)}
          </span>
        ) : null}
      </span>
    );
  }
  if (state === "off") return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 text-label font-semibold",
        state === "paused" ? "text-signal-amber-text" : "text-subtle-foreground",
      )}
    >
      <WifiOff className="h-4 w-4" aria-hidden />
      {state === "paused" ? copy.live.paused : "Connecting…"}
    </span>
  );
}
