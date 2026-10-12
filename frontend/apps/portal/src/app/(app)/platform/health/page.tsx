"use client";

import { useQuery } from "@tanstack/react-query";
import { formatNumber, formatRelative } from "@vtrs/core";
import { Card, CardHeader, Skeleton } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/chip";
import { InlineAlert, QueryError } from "@/components/ui/feedback";
import { PageHeader } from "@/components/vtrs/page-header";
import { ep } from "@/lib/api";

const LABEL: Record<string, string> = {
  database: "Database",
  cache: "Cache",
  broker: "Message broker",
  storage: "Evidence storage",
  outbox: "Event queue",
  audit_sealing: "Audit sealing",
  evidence: "Evidence processing",
};

type Component = Record<string, unknown> & { status?: string };

function describe(name: string, c: Component): string[] {
  const lines: string[] = [];
  if (typeof c.latency_ms === "number") lines.push(`Answers in ${c.latency_ms} ms`);
  if (typeof c.unpublished === "number") {
    lines.push(`${formatNumber(c.unpublished)} events waiting`);
    if (typeof c.oldest_seconds === "number")
      lines.push(`Oldest ${Math.round(c.oldest_seconds)} s`);
  }
  if (typeof c.unsealed === "number") {
    lines.push(`${formatNumber(c.unsealed)} audit entries not yet sealed`);
    if (typeof c.oldest_seconds === "number")
      lines.push(`Oldest ${Math.round(c.oldest_seconds)} s`);
  }
  if (typeof c.quarantined === "number")
    lines.push(`${formatNumber(c.quarantined)} photos in quarantine`);
  if (typeof c.detail === "string" && c.detail) lines.push(c.detail);
  return lines.length ? lines : [name === "evidence" ? "No uploads are stuck" : "Responding"];
}

export default function SystemHealth() {
  const health = useQuery({
    queryKey: ["platform", "health", "page"],
    queryFn: () => ep.admin.health(),
    refetchInterval: 15_000,
  });
  const data = health.data;

  return (
    <>
      <PageHeader
        title="System health"
        description="Is it up right now? Refreshes every 15 seconds."
      />
      {health.isError ? (
        <QueryError error={health.error} onRetry={() => void health.refetch()} />
      ) : !data ? (
        <Skeleton className="h-64" />
      ) : (
        <div className="flex flex-col gap-6">
          {data.status !== "ok" ? (
            <InlineAlert
              tone={data.status === "down" ? "danger" : "warning"}
              title="Something needs attention"
            >
              One or more services below are not fully healthy.
            </InlineAlert>
          ) : (
            <InlineAlert tone="success" title="Everything is responding">
              Checked {formatRelative(data.checked_at)}.
            </InlineAlert>
          )}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {Object.entries(data.components).map(([name, value]) => {
              const c = value as Component;
              const status = c.status ?? "ok";
              return (
                <Card key={name}>
                  <CardHeader
                    title={LABEL[name] ?? name.replace(/_/g, " ")}
                    actions={
                      <StatusChip
                        status={
                          status === "ok"
                            ? { label: "OK", tone: "teal", icon: "check-circle-2" }
                            : status === "degraded"
                              ? { label: "Slow", tone: "amber", icon: "alert-triangle" }
                              : { label: "Down", tone: "red", icon: "alert-circle" }
                        }
                      />
                    }
                  />
                  <ul className="flex flex-col gap-1 p-5 pt-0 text-body-sm text-subtle-foreground">
                    {describe(name, c).map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </Card>
              );
            })}
          </div>
        </div>
      )}
    </>
  );
}
