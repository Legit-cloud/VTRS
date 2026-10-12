"use client";

import { useQuery } from "@tanstack/react-query";
import {
  formatDateTime,
  formatNumber,
  formatPercent,
  reviewState,
  type AreaResult,
  type Level,
  type Measure,
} from "@vtrs/core";
import { ChevronRight, ClipboardCheck, ListChecks } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { StatusChip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/card";
import { EmptyState, QueryError } from "@/components/ui/feedback";
import { DataTable, type Column } from "@/components/vtrs/data-table";
import { PageHeader } from "@/components/vtrs/page-header";
import { ProvisionalBadge } from "@/components/vtrs/provisional";
import { PuDetailPanel } from "@/components/vtrs/pu-detail";
import { TallyMeter } from "@/components/vtrs/tally-meter";
import { ep } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { useContests, useElection } from "@/lib/election";
import { NEXT_LEVEL, isStart, startView } from "@/lib/scope-level";

interface Crumb {
  level: Level | "root";
  parent: string | null;
  name: string;
}

const LEVEL_NOUN: Record<Level, string> = { lga: "LGAs", ward: "Wards", pu: "Polling units" };

function ResultsInner() {
  const { me, can } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const { election } = useElection();
  const contests = useContests(election?.id);
  const [tab, setTab] = useState<"areas" | "review">("areas");
  const [measure, setMeasure] = useState<Measure | undefined>(undefined);
  const [open, setOpen] = useState<{ contest: string; pu: string } | null>(null);

  const start = startView(me?.scope);
  const startLevel: Level = start?.level ?? "lga";
  const contestId = params.get("contest") ?? contests.data?.[0]?.id ?? null;
  const levelParam = params.get("level") as Level | null;
  const level: Level = levelParam ?? startLevel;
  // With no explicit level we are at the top of the caller's scope, which may be one area.
  const parent = params.get("parent") ?? (levelParam ? null : (start?.parent ?? null));
  const name = params.get("name");

  // The areas stepped through on the way here. A deep link has no history, so the current
  // area (named in the URL) stands in for it.
  const [steps, setSteps] = useState<Crumb[]>([]);
  const trail: Crumb[] = isStart({ level, parent }, start)
    ? []
    : steps.some((c) => c.level === level && c.parent === parent)
      ? steps.slice(0, steps.findIndex((c) => c.level === level && c.parent === parent) + 1)
      : [...steps, { level, parent, name: name ?? "Area" }];

  const go = (nextLevel: Level, nextParent: string | null, label?: string) => {
    setSteps(() => {
      if (isStart({ level: nextLevel, parent: nextParent }, start)) return [];
      const existing = trail.findIndex((c) => c.level === nextLevel && c.parent === nextParent);
      if (existing >= 0) return trail.slice(0, existing + 1);
      return [...trail, { level: nextLevel, parent: nextParent, name: label ?? "Area" }];
    });
    const q = new URLSearchParams();
    if (contestId) q.set("contest", contestId);
    q.set("level", nextLevel);
    if (nextParent) q.set("parent", nextParent);
    if (label) q.set("name", label);
    router.push(`/results?${q.toString()}`);
  };

  const results = useQuery({
    queryKey: ["results", contestId, level, parent, measure],
    enabled: !!contestId,
    queryFn: () => ep.contests.results(contestId!, { level, parent_id: parent, measure }),
  });

  const queue = useQuery({
    queryKey: ["review-queue", election?.id],
    enabled: !!election?.review_enabled && can("results.review") && tab === "review",
    queryFn: async () => (await ep.review.queue(election!.id, { limit: 100 })).results,
  });

  const reviewEnabled = !!election?.review_enabled;
  const isPu = level === "pu";

  const columns: Column<AreaResult>[] = useMemo(() => {
    const cols: Column<AreaResult>[] = [
      {
        key: "name",
        header: LEVEL_NOUN[level].replace(/s$/, ""),
        cell: (r) => (
          <span className="font-semibold">
            {r.area_name}
            {isPu ? (
              <span className="mono ml-2 text-caption font-normal text-subtle-foreground">
                {r.area_code}
              </span>
            ) : null}
          </span>
        ),
        sortValue: (r) => r.area_name,
      },
    ];
    if (isPu) {
      cols.push({
        key: "status",
        header: "Status",
        cell: (r) =>
          r.status && r.status !== "NOT_REPORTED" ? (
            <StatusChip status={reviewState(r.status)} />
          ) : (
            <span className="text-subtle-foreground">Not reported</span>
          ),
        sortValue: (r) => r.status ?? "",
      });
    } else {
      cols.push({
        key: "reported",
        header: "Reported",
        numeric: true,
        cell: (r) => (
          <div className="flex items-center justify-end gap-4">
            {r.expected_pus <= 24 ? (
              <TallyMeter
                reported={r.reported_pus}
                total={r.expected_pus}
                caption={false}
                className="hidden xl:flex"
              />
            ) : null}
            <span className="w-16 text-right">
              {formatNumber(r.reported_pus)} / {formatNumber(r.expected_pus)}
            </span>
          </div>
        ),
        sortValue: (r) => r.reported_pct,
      });
      cols.push({
        key: "pct",
        header: "Coverage",
        numeric: true,
        cell: (r) => formatPercent(r.reported_pct),
        sortValue: (r) => r.reported_pct,
        hideOnNarrow: true,
      });
    }
    cols.push({
      key: "leader",
      header: "Leading",
      cell: (r) => {
        const top = [...r.votes].sort((a, b) => b.votes - a.votes)[0];
        if (!top || top.votes === 0) return <span className="text-subtle-foreground">–</span>;
        return (
          <span className="flex flex-wrap items-center gap-2">
            <span>
              {top.name} <span className="text-subtle-foreground">({top.party_acronym})</span>
            </span>
            <ProvisionalBadge />
          </span>
        );
      },
    });
    cols.push({
      key: "margin",
      header: "Margin",
      numeric: true,
      cell: (r) => (r.position.margin > 0 ? formatNumber(r.position.margin) : "–"),
      sortValue: (r) => r.position.margin,
      hideOnNarrow: true,
    });
    cols.push({
      key: "flags",
      header: "Anomalies",
      numeric: true,
      cell: (r) =>
        r.open_flags > 0 ? (
          <span className="font-semibold text-signal-red-text">{r.open_flags}</span>
        ) : (
          <span className="text-subtle-foreground">0</span>
        ),
      sortValue: (r) => r.open_flags,
    });
    return cols;
  }, [level, isPu]);

  const rows = results.data?.rows ?? [];

  if (!election) {
    return (
      <>
        <PageHeader title="Results" />
        <EmptyState
          icon={<ListChecks className="h-8 w-8" aria-hidden />}
          title="No election yet"
          description="Results by LGA, ward and polling unit appear here once an election is live."
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Results"
        description="Drill from LGA to ward to polling unit. Every figure is provisional."
        actions={
          <>
            {contests.data && contests.data.length > 1 ? (
              <select
                aria-label="Contest"
                value={contestId ?? ""}
                onChange={(e) => {
                  const q = new URLSearchParams();
                  q.set("contest", e.target.value);
                  q.set("level", startLevel);
                  router.push(`/results?${q.toString()}`);
                }}
                className="h-control rounded-md border-[1.5px] border-input bg-input-fill px-3 text-body"
              >
                {contests.data.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title}
                  </option>
                ))}
              </select>
            ) : null}
            {reviewEnabled ? (
              <div
                role="group"
                aria-label="Count"
                className="inline-flex rounded-md border border-border bg-card p-0.5"
              >
                {(["reported", "verified"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    aria-pressed={
                      (measure ??
                        (election.count_policy === "VERIFIED" ? "verified" : "reported")) === m
                    }
                    onClick={() => setMeasure(m)}
                    className={cn(
                      "h-8 rounded-sm px-3 text-label font-semibold capitalize",
                      (measure ??
                        (election.count_policy === "VERIFIED" ? "verified" : "reported")) === m
                        ? "bg-primary text-primary-foreground"
                        : "text-strong-foreground hover:bg-muted",
                    )}
                  >
                    {m}
                  </button>
                ))}
              </div>
            ) : null}
          </>
        }
      />

      {reviewEnabled && can("results.review") ? (
        <div role="tablist" aria-label="Results view" className="mb-4 flex gap-2">
          {(
            [
              ["areas", "By area"],
              ["review", "Awaiting review"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={cn(
                "h-control-dense rounded-full border px-4 text-label font-semibold",
                tab === key
                  ? "border-primary bg-primary-soft text-primary-soft-foreground"
                  : "border-border bg-card text-strong-foreground hover:bg-muted",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      ) : null}

      {tab === "areas" ? (
        <>
          <nav
            aria-label="Where you are"
            className="mb-4 flex flex-wrap items-center gap-1 text-body-sm"
          >
            <button
              type="button"
              className="rounded-sm font-semibold text-primary hover:underline"
              onClick={() => go(startLevel, start?.parent ?? null)}
              disabled={trail.length === 0}
            >
              {LEVEL_NOUN[startLevel]}
            </button>
            {trail.map((crumb, i) => (
              <span key={`${crumb.level}-${crumb.parent}`} className="flex items-center gap-1">
                <ChevronRight className="h-4 w-4 text-muted-foreground" aria-hidden />
                <button
                  type="button"
                  className={cn(
                    "rounded-sm hover:underline",
                    i === trail.length - 1 ? "font-semibold text-foreground" : "text-primary",
                  )}
                  onClick={() => go(crumb.level as Level, crumb.parent, crumb.name)}
                  disabled={i === trail.length - 1}
                >
                  {crumb.name}
                </button>
              </span>
            ))}
          </nav>

          {results.isLoading ? (
            <Skeleton className="h-72" />
          ) : results.isError ? (
            <QueryError error={results.error} onRetry={() => void results.refetch()} />
          ) : (
            <DataTable<AreaResult>
              caption={`${LEVEL_NOUN[level]} with reporting progress and provisional leaders`}
              columns={columns}
              rows={rows}
              rowKey={(r) => r.area_id}
              initialSort={{ key: "name", dir: "asc" }}
              onRowClick={(row) => {
                const next = NEXT_LEVEL[level];
                if (next) go(next, row.area_id, row.area_name);
                else if (contestId) setOpen({ contest: contestId, pu: row.area_id });
              }}
              empty={
                <EmptyState
                  icon={<ListChecks className="h-8 w-8" aria-hidden />}
                  title="Nothing to show here yet"
                  description="Areas appear as soon as polling units in your scope are part of this contest."
                />
              }
            />
          )}
          {results.data ? (
            <p className="mt-3 text-caption text-subtle-foreground">{results.data.notice}</p>
          ) : null}
        </>
      ) : (
        <ReviewQueue
          loading={queue.isLoading}
          error={queue.isError ? queue.error : null}
          onRetry={() => void queue.refetch()}
          items={queue.data ?? []}
          onOpen={(contest, pu) => setOpen({ contest, pu })}
        />
      )}

      <PuDetailPanel
        contestId={open?.contest ?? null}
        pollingUnitId={open?.pu ?? null}
        onClose={() => setOpen(null)}
        reviewEnabled={reviewEnabled}
      />
    </>
  );
}

function ReviewQueue({
  loading,
  error,
  onRetry,
  items,
  onOpen,
}: {
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  items: Awaited<ReturnType<typeof ep.review.queue>>["results"];
  onOpen: (contestId: string, pollingUnitId: string) => void;
}) {
  if (loading) return <Skeleton className="h-72" />;
  if (error) return <QueryError error={error} onRetry={onRetry} />;
  return (
    <DataTable
      caption="Results waiting for a decision"
      rows={items}
      rowKey={(i) => i.version_id}
      onRowClick={(i) => onOpen(i.contest_id, i.polling_unit_id)}
      initialSort={{ key: "received", dir: "asc" }}
      columns={[
        {
          key: "unit",
          header: "Polling unit",
          cell: (i) => (
            <span>
              <span className="font-semibold">{i.polling_unit_name}</span>
              <span className="mono ml-2 text-caption text-subtle-foreground">
                {i.polling_unit_code}
              </span>
            </span>
          ),
        },
        {
          key: "area",
          header: "Ward · LGA",
          cell: (i) => `${i.ward_name} · ${i.lga_name}`,
          hideOnNarrow: true,
        },
        {
          key: "valid",
          header: "Valid votes",
          numeric: true,
          cell: (i) => formatNumber(i.totals.valid),
        },
        {
          key: "flags",
          header: "Flags",
          numeric: true,
          cell: (i) =>
            i.flags.length ? (
              <span className="font-semibold text-signal-red-text">{i.flags.length}</span>
            ) : (
              "0"
            ),
          sortValue: (i) => i.flags.length,
        },
        {
          key: "state",
          header: "Status",
          cell: (i) => <StatusChip status={reviewState(i.state)} />,
        },
        {
          key: "received",
          header: "Received",
          cell: (i) => formatDateTime(i.server_received_at),
          sortValue: (i) => i.server_received_at,
          hideOnNarrow: true,
        },
      ]}
      empty={
        <EmptyState
          icon={<ClipboardCheck className="h-8 w-8" aria-hidden />}
          title="Nothing is waiting for review"
          description="Results that need a decision in your area appear here as agents send them."
        />
      }
    />
  );
}

export default function ResultsPage() {
  return (
    <Suspense>
      <ResultsInner />
    </Suspense>
  );
}
