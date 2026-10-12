import { Check } from "lucide-react";
import { flagStatus, formatRelative, ruleTitle, severity, type Flag } from "@vtrs/core";
import { cn } from "@/lib/cn";
import { StatusChip } from "@/components/ui/chip";

const bar: Record<string, string> = {
  blue: "bg-signal-blue-mark",
  amber: "bg-signal-amber-mark",
  red: "bg-signal-red-mark",
};

/** Left 4 px severity bar, severity chip, type, one-line reason, place, time. */
export function AnomalyCard({
  flag,
  selected,
  onSelect,
  compact,
}: {
  flag: Flag;
  selected?: boolean;
  onSelect?: () => void;
  compact?: boolean;
}) {
  const sev = severity(flag.severity);
  const status = flagStatus(flag.status);
  const closed = flag.status === "RESOLVED" || flag.status === "FALSE_POSITIVE";
  const Wrapper = onSelect ? "button" : "div";
  return (
    <Wrapper
      {...(onSelect ? { type: "button" as const, onClick: onSelect } : {})}
      aria-pressed={onSelect ? selected : undefined}
      className={cn(
        "relative flex w-full flex-col gap-1.5 overflow-hidden rounded-md border border-border py-3 pl-5 pr-4 text-left",
        closed ? "bg-muted" : "bg-card",
        selected && "border-primary ring-2 ring-primary/30",
        onSelect && "hover:bg-muted",
      )}
    >
      <span className={cn("absolute inset-y-0 left-0 w-1", bar[sev.tone] ?? bar.red)} aria-hidden />
      <div className="flex flex-wrap items-center gap-2">
        <StatusChip status={sev} />
        {closed ? (
          <span className="inline-flex items-center gap-1 text-caption font-semibold text-signal-teal-text">
            <Check className="h-3.5 w-3.5" aria-hidden /> {status.label}
          </span>
        ) : (
          <StatusChip status={status} />
        )}
        <span className="ml-auto text-caption text-subtle-foreground">
          {formatRelative(flag.created_at)}
        </span>
      </div>
      <p className="text-h3 font-semibold">{flag.title || ruleTitle(flag.rule_code)}</p>
      {compact || (flag.title || ruleTitle(flag.rule_code)) === ruleTitle(flag.rule_code) ? null : (
        <p className="text-body-sm text-strong-foreground">{ruleTitle(flag.rule_code)}</p>
      )}
      <p className="text-body-sm text-subtle-foreground">
        {flag.polling_unit_name} <span className="mono">({flag.polling_unit_code})</span> ·{" "}
        {flag.ward_name} · {flag.lga_name}
      </p>
    </Wrapper>
  );
}
