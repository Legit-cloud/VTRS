"use client";

import { useQuery } from "@tanstack/react-query";
import {
  formatNumber,
  formatPercent,
  formatTime,
  type AreaResult,
  type Candidate,
  type ContestSummary,
  type Measure,
} from "@vtrs/core";
import { Gauge, Moon, Sun } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Skeleton } from "@/components/ui/card";
import { EmptyState, QueryError } from "@/components/ui/feedback";
import { AnomalyCard } from "@/components/vtrs/anomaly-card";
import { CandidateBars, type BarRow } from "@/components/vtrs/candidate-bar";
import { CoverageChart, CoverageGrid, coverageStyle } from "@/components/vtrs/coverage";
import { LiveIndicator } from "@/components/vtrs/live-indicator";
import { PageHeader } from "@/components/vtrs/page-header";
import { ProvisionalBadge } from "@/components/vtrs/provisional";
import { StatTile } from "@/components/vtrs/stat-tile";
import { ep } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { useElection } from "@/lib/election";
import { useLiveUpdates } from "@/lib/live";
import { NEXT_LEVEL, startView } from "@/lib/scope-level";
import { useWarRoomTheme } from "@/lib/war-room-theme";

function useDashboard(electionId: string | undefined, measure: Measure | undefined) {
  return useQuery({
    queryKey: ["dash", electionId, measure ?? "default"],
    enabled: !!electionId,
    queryFn: () => ep.dashboard(electionId!, measure),
  });
}

export default function WarRoomPage() {
  const { me, can } = useAuth();
  const router = useRouter();
  const { election, loading: electionLoading } = useElection();
  const { dark, toggle } = useWarRoomTheme();
  const [measure, setMeasure] = useState<Measure | undefined>(undefined);
  const [contestId, setContestId] = useState<string | null>(null);

  const live = useLiveUpdates(
    election?.id ?? null,
    election?.status === "LIVE" || election?.status === "CLOSED",
  );
  const dashboard = useDashboard(election?.id, measure);

  const contests = useMemo(() => dashboard.data?.contests ?? [], [dashboard.data]);
  const contest: ContestSummary | undefined =
    contests.find((c) => c.contest_id === contestId) ?? contests[0];

  const start = startView(me?.scope);
  const childLevel = start?.level ?? null;
  // Where a tile leads: the next level down, or the polling units of the ward you are in.
  const openArea = (row: { area_id: string; area_name: string }) => {
    const next = childLevel ? NEXT_LEVEL[childLevel] : null;
    const q = new URLSearchParams({ contest: contest!.contest_id });
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
  const effectiveMeasure = (dashboard.data?.measure as Measure | undefined) ?? measure;

  const areas = useQuery({
    queryKey: ["results", contest?.contest_id, childLevel, start?.parent, effectiveMeasure],
    enabled: !!contest && !!childLevel,
    queryFn: () =>
      ep.contests.results(contest!.contest_id, {
        level: childLevel!,
        parent_id: start?.parent,
        measure: effectiveMeasure,
      }),
  });

  const timeline = useQuery({
    queryKey: ["dash", "coverage", contest?.contest_id],
    enabled: !!contest,
    queryFn: () => ep.contests.coverage(contest!.contest_id, { interval: "hour" }),
  });

  const flags = useQuery({
    queryKey: ["flags", election?.id, "open-feed"],
    enabled: !!election && can("anomalies.view"),
    queryFn: async () => (await ep.flags.list(election!.id, { status: "OPEN", limit: 6 })).results,
  });

  const candidates = useQuery({
    queryKey: ["candidates", contest?.contest_id],
    enabled: !!contest,
    retry: false,
    queryFn: async (): Promise<Candidate[]> => {
      const data = await ep.contests.candidates(contest!.contest_id);
      return Array.isArray(data) ? data : data.results;
    },
  });

  const bars: BarRow[] = useMemo(() => {
    if (!contest) return [];
    const own = new Set((candidates.data ?? []).filter((c) => c.is_own_party).map((c) => c.id));
    return [...contest.votes]
      .sort((a, b) => b.votes - a.votes)
      .map((v) => ({
        id: v.candidate_id,
        name: v.name,
        party: v.party_acronym,
        votes: v.votes,
        own: own.has(v.candidate_id),
        leader: contest.position.leader_id === v.candidate_id && !contest.position.is_tie,
      }));
  }, [contest, candidates.data]);

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

  const leader = contest?.votes.find((v) => v.candidate_id === contest.position.leader_id);
  const asOf = contest?.updated_at ? new Date(contest.updated_at).getTime() : null;
  const stale = live.state !== "live" && live.state !== "off";

  const ledger = [...(areas.data?.rows ?? [])].sort((a, b) => a.reported_pct - b.reported_pct);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card px-5 py-3">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          <h1 className="truncate text-h2">{election.name}</h1>
          {contest ? (
            <span className="text-body text-subtle-foreground">{contest.title}</span>
          ) : null}
          <LiveIndicator state={live.state} asOf={asOf} />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <ProvisionalBadge />
          {asOf ? (
            <span className="text-body-sm text-subtle-foreground tabular-nums">
              as of {formatTime(asOf)}
            </span>
          ) : null}
          {dashboard.data?.review_enabled ? (
            <div
              role="group"
              aria-label="Count"
              className="inline-flex rounded-md border border-border p-0.5"
            >
              {(["reported", "verified"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMeasure(m)}
                  aria-pressed={effectiveMeasure === m}
                  className={cn(
                    "h-7 rounded-sm px-3 text-label font-semibold capitalize",
                    effectiveMeasure === m
                      ? "bg-primary text-primary-foreground"
                      : "text-strong-foreground hover:bg-muted",
                  )}
                >
                  {m}
                </button>
              ))}
            </div>
          ) : null}
          <Button
            variant="outline"
            size="icon-sm"
            onClick={toggle}
            aria-label={dark ? "Switch to the light theme" : "Switch to the War Room theme"}
          >
            {dark ? (
              <Sun className="h-4 w-4" aria-hidden />
            ) : (
              <Moon className="h-4 w-4" aria-hidden />
            )}
          </Button>
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

      {contests.length > 1 ? (
        <div role="tablist" aria-label="Contest" className="flex flex-wrap gap-2">
          {contests.map((c) => (
            <button
              key={c.contest_id}
              role="tab"
              aria-selected={c.contest_id === contest?.contest_id}
              onClick={() => setContestId(c.contest_id)}
              className={cn(
                "h-control-dense rounded-full border px-4 text-label font-semibold",
                c.contest_id === contest?.contest_id
                  ? "border-primary bg-primary-soft text-primary-soft-foreground"
                  : "border-border bg-card text-strong-foreground hover:bg-muted",
              )}
            >
              {c.title}
            </button>
          ))}
        </div>
      ) : null}

      {dashboard.isLoading ? <WarRoomSkeleton /> : null}

      {!dashboard.isLoading && !contest ? (
        <EmptyState
          icon={<Gauge className="h-8 w-8" aria-hidden />}
          title="No contests in this election"
          description="Results appear here once a contest is added and the election goes live."
        />
      ) : null}

      {contest ? (
        <>
          <section
            aria-label="Headline figures"
            className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4"
          >
            <StatTile
              emphasized
              value={formatPercent(contest.reported_pct)}
              label="Polling units reported"
              detail={`${formatNumber(contest.reported_pus)} of ${formatNumber(contest.expected_pus)}`}
              progress={contest.reported_pct}
            />
            <StatTile
              value={contest.position.is_tie ? "Tied" : leader ? leader.name : "No results yet"}
              label="Leading"
              detail={
                leader ? `${leader.party_acronym} · ${formatNumber(leader.votes)} votes` : undefined
              }
              badge={leader || contest.position.is_tie ? <ProvisionalBadge /> : undefined}
              className="[&_.text-numeral]:text-h1 [&_.text-numeral]:leading-tight"
            />
            <StatTile
              value={contest.position.margin > 0 ? formatNumber(contest.position.margin) : "–"}
              label="Margin in votes"
              detail={
                contest.position.margin_pct != null && contest.position.margin > 0
                  ? `${formatPercent(contest.position.margin_pct)} of votes counted`
                  : undefined
              }
              badge={contest.position.margin > 0 ? <ProvisionalBadge /> : undefined}
            />
            <StatTile
              value={formatNumber(contest.open_flags)}
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

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
            <Card className="xl:col-span-8">
              <CardHeader
                title={
                  childLevel === "lga"
                    ? "Coverage by LGA"
                    : childLevel === "ward"
                      ? "Coverage by ward"
                      : "Coverage by polling unit"
                }
                description="Share of polling units that have reported. Select an area to open it."
              />
              <div className="p-5 pt-2">
                {areas.isLoading ? (
                  <Skeleton className="h-64" />
                ) : areas.isError ? (
                  <QueryError error={areas.error} onRetry={() => void areas.refetch()} />
                ) : childLevel ? (
                  <CoverageGrid
                    rows={areas.data?.rows ?? []}
                    onSelect={(row: AreaResult) => router.push(openArea(row))}
                  />
                ) : (
                  <p className="text-body text-subtle-foreground">
                    Your account covers individual polling units. Open Results to see them.
                  </p>
                )}
              </div>
            </Card>

            <Card className="xl:col-span-4">
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

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <Card>
              <CardHeader
                title="Candidate results"
                description={`${formatNumber(contest.position.total_votes)} valid votes counted so far`}
              />
              <div className="p-5 pt-2">
                {bars.length === 0 ? (
                  <p className="text-body text-subtle-foreground">
                    Votes appear as results are reported.
                  </p>
                ) : (
                  <CandidateBars rows={bars} />
                )}
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
                  expected={timeline.data?.expected_pus ?? contest.expected_pus}
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
