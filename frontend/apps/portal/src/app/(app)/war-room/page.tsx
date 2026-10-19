"use client";

import { useQuery } from "@tanstack/react-query";
import { formatNumber, formatPercent, formatTime, type AreaResult, type Measure } from "@vtrs/core";
import { Gauge } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Skeleton } from "@/components/ui/card";
import { EmptyState, QueryError } from "@/components/ui/feedback";
import { AnomalyCard } from "@/components/vtrs/anomaly-card";
import { areaColumns } from "@/components/vtrs/area-table";
import {
  ContestantBars,
  LeaderChip,
  toContestantRows,
} from "@/components/vtrs/contestant-bar";
import { CoverageChart, CoverageGrid, coverageStyle } from "@/components/vtrs/coverage";
import { DataTable } from "@/components/vtrs/data-table";
import { LiveIndicator } from "@/components/vtrs/live-indicator";
import { MeasureToggle } from "@/components/vtrs/measure-toggle";
import { PageHeader } from "@/components/vtrs/page-header";
import { ProvisionalBadge } from "@/components/vtrs/provisional";
import { StatTile } from "@/components/vtrs/stat-tile";
import { ep } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useElection } from "@/lib/election";
import { useLiveUpdates } from "@/lib/live";
import { NEXT_LEVEL, startView } from "@/lib/scope-level";

export default function WarRoomPage() {
  const { me, can } = useAuth();
  const router = useRouter();
  const { election, loading: electionLoading } = useElection();
  const [measure, setMeasure] = useState<Measure | undefined>(undefined);

  const live = useLiveUpdates(
    election?.id ?? null,
    election?.status === "LIVE" || election?.status === "CLOSED",
  );
  const dashboard = useQuery({
    queryKey: ["dash", election?.id, measure ?? "default"],
    enabled: !!election,
    queryFn: () => ep.dashboard(election!.id, measure),
  });
  // The election's count policy picks the default; the toggle overrides it. The API names the
  // measure in capitals (REPORTED); queries and the toggle use lower case.
  const effectiveMeasure =
    (dashboard.data?.measure?.toLowerCase() as Measure | undefined) ?? measure;

  const start = startView(me?.scope);
  const childLevel = start?.level ?? null;
  // Where a row leads: the next level down, or the polling units of the ward you are in.
  const openArea = (row: { area_id: string; area_name: string }) => {
    const next = childLevel ? NEXT_LEVEL[childLevel] : null;
    const q = new URLSearchParams();
    if (next) {
      q.set("level", next);
      q.set("parent", row.area_id);
      q.set("name", row.area_name);
    } else {
      q.set("level", "pu");
      if (start?.parent) q.set("parent", start.parent);
    }
    return `/results?${q.toString()}`;
  };

  const areas = useQuery({
    queryKey: ["results", election?.id, childLevel, start?.parent, effectiveMeasure],
    enabled: !!election && !!childLevel && !!dashboard.data,
    queryFn: () =>
      ep.elections.results(election!.id, {
        level: childLevel!,
        parent_id: start?.parent,
        measure: effectiveMeasure,
      }),
  });

  const timeline = useQuery({
    queryKey: ["dash", "coverage", election?.id],
    enabled: !!election,
    queryFn: () => ep.elections.coverage(election!.id, { interval: "hour" }),
  });

  const flags = useQuery({
    queryKey: ["flags", election?.id, "open-feed"],
    enabled: !!election && can("anomalies.view"),
    queryFn: async () => (await ep.flags.list(election!.id, { status: "OPEN", limit: 6 })).results,
  });

  const parties = useMemo(() => dashboard.data?.parties ?? [], [dashboard.data]);
  const summary = dashboard.data?.summary;
  const rows = useMemo(
    () => (summary ? toContestantRows(summary.votes, parties) : []),
    [summary, parties],
  );

  if (electionLoading) return <WarRoomSkeleton />;

  if (!election) {
    return (
      <>
        <PageHeader title="War Room" />
        <EmptyState
          icon={<Gauge className="h-8 w-8" aria-hidden />}
          title="No election to show yet"
          description="When an election is set up for your party, its live results appear here."
          action={
            can("elections.configure") ? (
              <Link href="/elections">
                <Button>Set up an election</Button>
              </Link>
            ) : undefined
          }
        />
      </>
    );
  }

  const position = summary?.position;
  const asOf = summary?.updated_at ? new Date(summary.updated_at).getTime() : null;
  const stale = live.state !== "live" && live.state !== "off";
  const areaRows = areas.data?.rows ?? [];
  const ledger = [...areaRows].sort((a, b) => a.reported_pct - b.reported_pct);
  const own = parties.find((p) => p.is_own);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card px-5 py-3">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          <h1 className="truncate text-h2">{election.name}</h1>
          <span className="text-body text-subtle-foreground">{election.election_type_name}</span>
          <LiveIndicator state={live.state} asOf={asOf} />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <ProvisionalBadge />
          {asOf ? (
            <span className="text-body-sm text-subtle-foreground tabular-nums">
              as of {formatTime(asOf)}
            </span>
          ) : null}
          <MeasureToggle value={effectiveMeasure} onChange={setMeasure} />
        </div>
      </div>

      {stale ? (
        <p
          role="status"
          className="rounded-md bg-signal-amber-soft px-4 py-2 text-body-sm font-medium text-signal-amber-text"
        >
          Live updates paused. Reconnecting… Figures are as of{" "}
          {asOf ? formatTime(asOf) : "the last refresh"}.
        </p>
      ) : null}

      {dashboard.isError ? (
        <QueryError error={dashboard.error} onRetry={() => void dashboard.refetch()} />
      ) : null}

      {dashboard.isLoading ? <WarRoomSkeleton /> : null}

      {!dashboard.isLoading && dashboard.data && parties.length === 0 ? (
        <EmptyState
          icon={<Gauge className="h-8 w-8" aria-hidden />}
          title="No contesting parties yet"
          description="Results appear here once the parties and their candidates are set up and the election goes live."
        />
      ) : null}

      {summary && position && parties.length > 0 ? (
        <>
          <section
            aria-label="Headline figures"
            className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4"
          >
            <StatTile
              emphasized
              value={formatPercent(summary.reported_pct)}
              label="Polling units reported"
              detail={`${formatNumber(summary.reported_pus)} of ${formatNumber(summary.expected_pus)} · ${formatNumber(summary.verified_pus)} verified`}
              progress={summary.reported_pct}
            />
            <StatTile
              value={<LeaderChip position={position} parties={parties} className="text-body" />}
              label="Leading"
              detail={
                position.status === "LEADING" || position.status === "NARROW"
                  ? `${formatNumber(position.total_votes)} votes counted`
                  : undefined
              }
              badge={position.status !== "NO_VOTES" ? <ProvisionalBadge /> : undefined}
            />
            <StatTile
              value={
                position.status === "LEADING" || position.status === "NARROW"
                  ? formatNumber(position.margin)
                  : "–"
              }
              label="Margin in votes"
              detail={
                own && position.own_margin != null
                  ? `${own.abbreviation} ${position.own_margin >= 0 ? "ahead by" : "behind by"} ${formatNumber(Math.abs(position.own_margin))}`
                  : position.margin_pct != null && position.margin > 0
                    ? `${formatPercent(position.margin_pct)} of votes counted`
                    : undefined
              }
            />
            <StatTile
              value={formatNumber(summary.open_flags)}
              label="Open anomalies"
              detail={
                can("anomalies.view") ? (
                  <Link href="/anomalies" className="font-semibold text-primary">
                    Review anomalies
                  </Link>
                ) : undefined
              }
            />
          </section>

          <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-12">
            <Card className="xl:col-span-7">
              <CardHeader
                title="Contestants side by side"
                description={`${formatNumber(position.total_votes)} valid votes counted so far, ${effectiveMeasure === "verified" ? "verified results only" : "all results"}`}
              />
              <div className="p-5 pt-2">
                {rows.length === 0 ? (
                  <p className="text-body text-subtle-foreground">
                    Votes appear as results are reported.
                  </p>
                ) : (
                  <ContestantBars rows={rows} position={position} />
                )}
              </div>
            </Card>

            <Card className="xl:col-span-5">
              <CardHeader
                title="New anomalies"
                actions={
                  can("anomalies.view") ? (
                    <Link href="/anomalies" className="text-label font-semibold text-primary">
                      See all
                    </Link>
                  ) : undefined
                }
              />
              <div className="flex flex-col gap-2 p-5 pt-2">
                {flags.isLoading ? (
                  <Skeleton className="h-40" />
                ) : (flags.data ?? []).length === 0 ? (
                  <p className="text-body text-subtle-foreground">
                    No anomalies in your area. New flags appear here as results come in.
                  </p>
                ) : (
                  flags.data!.map((flag) => <AnomalyCard key={flag.id} flag={flag} compact />)
                )}
              </div>
            </Card>
          </div>

          {childLevel ? (
            <Card>
              <CardHeader
                title={
                  childLevel === "lga"
                    ? "By LGA"
                    : childLevel === "ward"
                      ? "By ward"
                      : "By polling unit"
                }
                description="Each area's votes per party and who leads it. The bar shows the leader's colour; ties and narrow margins are named."
              />
              <div className="p-5 pt-2">
                {areas.isLoading ? (
                  <Skeleton className="h-64" />
                ) : areas.isError ? (
                  <QueryError error={areas.error} onRetry={() => void areas.refetch()} />
                ) : (
                  <DataTable<AreaResult>
                    caption="Results by area"
                    columns={areaColumns(childLevel, parties)}
                    rows={areaRows}
                    rowKey={(r) => r.area_id}
                    onRowClick={(r) => router.push(openArea(r))}
                    initialSort={{ key: "name", dir: "asc" }}
                    empty="No areas in your scope yet."
                  />
                )}
              </div>
            </Card>
          ) : (
            <Card>
              <div className="p-5">
                <p className="text-body text-subtle-foreground">
                  Your account covers individual polling units. Open Results to see them.
                </p>
              </div>
            </Card>
          )}

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <Card>
              <CardHeader
                title="Coverage"
                description="Share of polling units that have reported. Select an area to open it."
              />
              <div className="p-5 pt-2">
                {areas.isLoading ? (
                  <Skeleton className="h-64" />
                ) : childLevel ? (
                  <CoverageGrid
                    rows={areaRows}
                    onSelect={(row: AreaResult) => router.push(openArea(row))}
                  />
                ) : null}
              </div>
            </Card>
            <Card>
              <CardHeader
                title="Reporting over time"
                description="Cumulative share of polling units reported, against the 95% target."
              />
              <div className="p-5 pt-2">
                <CoverageChart
                  points={timeline.data?.points ?? []}
                  expected={timeline.data?.expected_pus ?? summary.expected_pus}
                />
              </div>
            </Card>
          </div>

          {ledger.length > 0 ? (
            <section aria-label="Scorecards">
              <h2 className="mb-3 text-h2">Lowest coverage first</h2>
              <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {ledger.slice(0, 12).map((row) => {
                  const style = coverageStyle(row.reported_pct, row.reported_pus);
                  return (
                    <li key={row.area_id}>
                      <Link
                        href={openArea(row)}
                        className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4 shadow-card hover:bg-muted"
                      >
                        <span className="text-body font-semibold">{row.area_name}</span>
                        <span className="flex items-baseline justify-between">
                          <span className="tabular-nums text-h2 font-bold">
                            {formatPercent(row.reported_pct)}
                          </span>
                          <span className="text-caption text-subtle-foreground tabular-nums">
                            {formatNumber(row.reported_pus)} of {formatNumber(row.expected_pus)}
                          </span>
                        </span>
                        <LeaderChip position={row.position} parties={parties} />
                        <span className="text-caption text-subtle-foreground">
                          {style.label}
                          {row.open_flags > 0
                            ? ` · ${row.open_flags} open ${row.open_flags === 1 ? "anomaly" : "anomalies"}`
                            : ""}
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function WarRoomSkeleton() {
  return (
    <div className="flex flex-col gap-6" aria-busy="true" aria-label="Loading the War Room">
      <Skeleton className="h-14" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-32" />
        ))}
      </div>
      <Skeleton className="h-80" />
    </div>
  );
}
