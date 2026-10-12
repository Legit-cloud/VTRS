import { AlertCircle, AlertTriangle, CheckCircle2, Info, WifiOff } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError } from "@vtrs/core";
import { cn } from "@/lib/cn";
import { Button } from "./button";

type AlertTone = "info" | "success" | "warning" | "danger";

const alertStyles: Record<AlertTone, { bar: string; fill: string; Icon: typeof Info }> = {
  info: { bar: "bg-signal-blue-mark", fill: "bg-signal-blue-soft", Icon: Info },
  success: { bar: "bg-signal-teal-mark", fill: "bg-signal-teal-soft", Icon: CheckCircle2 },
  warning: { bar: "bg-signal-amber-mark", fill: "bg-signal-amber-soft", Icon: AlertTriangle },
  danger: { bar: "bg-signal-red-mark", fill: "bg-signal-red-soft", Icon: AlertCircle },
};

/** Inline alert: 4 px bar in the signal colour, soft fill, icon, title, one sentence, action. */
export function InlineAlert({
  tone = "info",
  title,
  children,
  action,
  className,
}: {
  tone?: AlertTone;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const { bar, fill, Icon } = alertStyles[tone];
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cn(
        "relative flex gap-3 overflow-hidden rounded-md py-3 pl-5 pr-4",
        fill,
        className,
      )}
    >
      <span className={cn("absolute inset-y-0 left-0 w-1", bar)} aria-hidden />
      <Icon className="mt-0.5 h-5 w-5 shrink-0 text-foreground" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-label text-foreground">{title}</p>
        {children ? (
          <div className="mt-0.5 text-body-sm text-strong-foreground">{children}</div>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn("relative overflow-hidden rounded-lg border border-border bg-card", className)}
    >
      <div className="tally-bg absolute inset-0 opacity-60" aria-hidden />
      <div className="relative flex flex-col items-center gap-3 px-6 py-12 text-center">
        <span className="flex h-16 w-16 items-center justify-center rounded-full bg-primary-soft text-primary">
          {icon}
        </span>
        <h3 className="text-h3">{title}</h3>
        <p className="max-w-md text-body text-subtle-foreground">{description}</p>
        {action}
      </div>
    </div>
  );
}

/** A failed read: say what happened in plain words and offer the retry. */
export function QueryError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const apiError = error instanceof ApiError ? error : null;
  const offline = apiError?.isNetwork;
  return (
    <InlineAlert
      tone={offline ? "warning" : "danger"}
      title={offline ? "Can't reach the server" : "This didn't load"}
      action={
        onRetry ? (
          <Button size="sm" variant="outline" onClick={onRetry}>
            Try again
          </Button>
        ) : undefined
      }
    >
      {offline
        ? "Check your connection. What you saw before is still on screen."
        : (apiError?.detail ?? "Something went wrong. Try again in a moment.")}
    </InlineAlert>
  );
}

export function OfflineNotice() {
  return (
    <InlineAlert tone="warning" title="You're offline">
      <span className="inline-flex items-center gap-1">
        <WifiOff className="h-4 w-4" aria-hidden /> Showing what was last loaded.
      </span>
    </InlineAlert>
  );
}
