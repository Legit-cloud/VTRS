"use client";

import { useQuery } from "@tanstack/react-query";
import {
  formatDateTime,
  formatNumber,
  reviewState,
  SUBMISSION_STATUS,
  type AreaResult,
  type Level,
  type Measure,
} from "@vtrs/core";
import { ChevronRight, ClipboardCheck, ListChecks } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { StatusChip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/card";
import { EmptyState, QueryError } from "@/components/ui/feedback";
import { areaColumns } from "@/components/vtrs/area-table";
import { DataTable } from "@/components/vtrs/data-table";
import { MeasureToggle } from "@/components/vtrs/measure-toggle";
import { PageHeader } from "@/components/vtrs/page-header";
import { PuDetailPanel } from "@/components/vtrs/pu-detail";
import { ep } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { useElection } from "@/lib/election";
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
  const [tab, setTab] = useState<"areas" | "review">("areas");
  const [measure, setMeasure] = useState<Measure | undefined>(undefined);
  const [open, setOpen] = useState<string | null>(null);

  const start = startView(me?.scope);
  const startLevel: Level = start?.level ?? "lga";
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
    q.set("level", nextLevel);
    if (nextParent) q.set("parent", nextParent);
    if (label) q.set("name", label);
    router.push(`/results?${q.toString()}`);
  };

  const results = useQuery({
    queryKey: ["results", election?.id, level, parent, measure],
    enabled: !!election,
    queryFn: () => ep.elections.results(election!.id, { level, parent_id: parent, measure }),
  });

  const queue = useQuery({
    queryKey: ["review-queue", election?.id],
    enabled: !!election && can("results.review") && tab === "review",
    queryFn: async () => (await ep.review.queue(election!.id, { limit: 100 })).results,
  });

  const parties = results.data?.parties ?? [];
  const effectiveMeasure =
    (results.data?.measure?.toLowerCase() as Measure | undefined) ??
    measure ??
    (election?.count_policy === "VERIFIED" ? "verified" : "reported");

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
        description="Drill from LGA to ward to polling unit, with every party's votes. Every figure is provisional."
        actions={<MeasureToggle value={effectiveMeasure} onChange={setMeasure} />}
      />

      {can("results.review") ? (
        <div role="tablist" aria-label="Results view" className="mb-4 flex gap-2">
          {(
            [
              ["areas", "By area"],
              ["review", "To verify"],
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
              caption={`${LEVEL_NOUN[level]} with each party's votes and the provisional leader`}
              columns={areaColumns(level, parties)}
              rows={rows}
              rowKey={(r) => r.area_id}
              initialSort={{ key: "name", dir: "asc" }}
              onRowClick={(row) => {
                const next = NEXT_LEVEL[level];
                if (next) go(next, row.area_id, row.area_name);
                else setOpen(row.area_id);
              }}
              empty={
                <EmptyState
                  icon={<ListChecks className="h-8 w-8" aria-hidden />}
                  title="Nothing to show here yet"
                  description="Areas appear as soon as polling units in your scope are mapped to this election's constituencies."
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
          onOpen={(pu) => setOpen(pu)}
        />
      )}

      <PuDetailPanel
        electionId={open ? (election?.id ?? null) : null}
        pollingUnitId={open}
        onClose={() => setOpen(null)}
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
  onOpen: (pollingUnitId: string) => void;
}) {
  if (loading) return <Skeleton className="h-72" />;
  if (error) return <QueryError error={error} onRetry={onRetry} />;
  return (
    <DataTable
      caption="Results waiting for a decision"
      rows={items}
      rowKey={(i) => i.version_id}
      onRowClick={(i) => onOpen(i.polling_unit_id)}
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
          cell: (i) => (
            <span className="flex flex-wrap gap-1">
              <StatusChip status={reviewState(i.state)} />
              <StatusChip
                status={SUBMISSION_STATUS[i.completion === "COMPLETE" ? "COMPLETE" : "NUMBERS_SUBMITTED"]}
              />
            </span>
          ),
          sortValue: (i) => i.completion,
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
          title="Nothing is waiting to be verified"
          description="Every result is unverified until a coordinator checks it against its sheet. New results in your area appear here."
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
