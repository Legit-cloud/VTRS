"use client";

import { useQuery } from "@tanstack/react-query";
import { formatNumber, formatPercent, formatRelative } from "@vtrs/core";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { Card, CardHeader, Skeleton } from "@/components/ui/card";
import { QueryError } from "@/components/ui/feedback";
import { PageHeader } from "@/components/vtrs/page-header";
import { StatTile } from "@/components/vtrs/stat-tile";
import { ep } from "@/lib/api";

const ATTENTION_LINK: Record<string, string> = {
  verification: "/platform/verification",
  messaging: "/platform/messaging",
  queue: "/platform/health",
  evidence: "/platform/health",
};

export default function PlatformOverview() {
  const overview = useQuery({
    queryKey: ["platform", "overview"],
    queryFn: () => ep.platform.overview(),
    refetchInterval: 30_000,
  });
  const health = useQuery({
    queryKey: ["platform", "health"],
    queryFn: () => ep.admin.health(),
    refetchInterval: 30_000,
  });
  const o = overview.data;
  const perHourPct = o ? (o.submissions.last_hour / o.submissions.target_per_hour) * 100 : 0;

  return (
    <>
      <PageHeader
        title="Overview"
        description="Is the platform healthy, and who needs attention?"
      />
      {overview.isError ? (
        <QueryError error={overview.error} onRetry={() => void overview.refetch()} />
      ) : !o ? (
        <Skeleton className="h-64" />
      ) : (
        <div className="flex flex-col gap-6">
          <section
            aria-label="Platform figures"
            className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3"
          >
            <StatTile
              emphasized
              value={formatNumber(o.organizations.active)}
              label="Active organisations"
              detail={`${formatNumber(o.organizations.pending_approval)} waiting for approval`}
            />
            <StatTile
              value={formatNumber(o.agents)}
              label="Agents on the platform"
              detail={`${formatNumber(o.elections.live)} live ${o.elections.live === 1 ? "election" : "elections"}`}
            />
            <StatTile
              value={formatNumber(o.submissions.last_hour)}
              label="Results received in the last hour"
              detail={`Target ${formatNumber(o.submissions.target_per_hour)} per hour`}
              progress={Math.min(100, perHourPct)}
            />
            <StatTile value={formatNumber(o.open_flags)} label="Open anomalies, all parties" />
            <StatTile
              value={formatNumber(o.messaging_failed_last_hour)}
              label="Messages that failed in the last hour"
              detail={
                <Link href="/platform/messaging" className="font-semibold text-primary">
                  See delivery rates
                </Link>
              }
            />
            <StatTile
              value={formatPercent(
                o.organizations.active + o.organizations.suspended > 0
                  ? (o.organizations.active /
                      (o.organizations.active + o.organizations.suspended)) *
                      100
                  : 100,
              )}
              label="Of approved organisations in good standing"
              detail={`${formatNumber(o.organizations.suspended)} suspended`}
            />
          </section>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <Card>
              <CardHeader title="Needs attention" />
              <div className="flex flex-col gap-2 p-5 pt-2">
                {o.needs_attention.length === 0 ? (
                  <p className="flex items-center gap-2 text-body text-subtle-foreground">
                    <CheckCircle2 className="h-5 w-5 text-signal-teal-text" aria-hidden />
                    Nothing is waiting on you.
                  </p>
                ) : (
                  o.needs_attention.map((item) => (
                    <Link
                      key={item.kind}
                      href={ATTENTION_LINK[item.kind] ?? "/platform"}
                      className="flex items-center gap-3 rounded-md border border-border p-3 hover:bg-muted"
                    >
                      <AlertTriangle className="h-5 w-5 text-signal-amber-text" aria-hidden />
                      <span className="tabular-nums text-h3 font-bold">
                        {formatNumber(item.count)}
                      </span>
                      <span className="text-body">{item.text}</span>
                    </Link>
                  ))
                )}
              </div>
            </Card>
            <Card>
              <CardHeader
                title="Services"
                description={
                  health.data ? `Checked ${formatRelative(health.data.checked_at)}` : undefined
                }
                actions={
                  <Link href="/platform/health" className="text-label font-semibold text-primary">
                    Details
                  </Link>
                }
              />
              <div className="p-5 pt-2">
                {health.isLoading ? (
                  <Skeleton className="h-32" />
                ) : health.isError ? (
                  <QueryError error={health.error} onRetry={() => void health.refetch()} />
                ) : (
                  <ul className="grid grid-cols-2 gap-3">
                    {Object.entries(health.data!.components).map(([name, value]) => {
                      const status = String((value as { status?: unknown }).status ?? "ok");
                      return (
                        <li
                          key={name}
                          className="flex items-center justify-between rounded-md bg-muted px-3 py-2 text-body-sm"
                        >
                          <span className="capitalize">{name.replace(/_/g, " ")}</span>
                          <span
                            className={
                              status === "ok"
                                ? "font-semibold text-signal-teal-text"
                                : status === "degraded"
                                  ? "font-semibold text-signal-amber-text"
                                  : "font-semibold text-signal-red-text"
                            }
                          >
                            {status === "ok" ? "OK" : status === "degraded" ? "Slow" : "Down"}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
