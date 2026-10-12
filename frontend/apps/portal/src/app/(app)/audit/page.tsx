"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { cursorFrom, formatDateTime, type AuditEvent } from "@vtrs/core";
import { History } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/card";
import { EmptyState, QueryError } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/field";
import { PageHeader } from "@/components/vtrs/page-header";
import { Timeline } from "@/components/vtrs/timeline";
import { ep } from "@/lib/api";

const OBJECT_TYPES = [
  ["", "Everything"],
  ["result_version", "Results"],
  ["anomaly_flag", "Anomalies"],
  ["election", "Elections"],
  ["contest", "Contests"],
  ["candidate", "Candidates"],
  ["user", "People"],
  ["invitation", "Invitations"],
  ["device", "Devices"],
  ["assignment", "Assignments"],
  ["export_job", "Exports"],
  ["alert_policy", "Alert policy"],
  ["session", "Sign-ins"],
];

const todayLagos = () => new Date(Date.now() + 3600_000).toISOString().slice(0, 10);

/** Dates are Africa/Lagos days; the API takes instants. */
const startOf = (day: string) => new Date(`${day}T00:00:00+01:00`).toISOString();
const endOf = (day: string) => new Date(`${day}T23:59:59.999+01:00`).toISOString();

export default function AuditPage() {
  const [from, setFrom] = useState(todayLagos());
  const [to, setTo] = useState(todayLagos());
  const [objectType, setObjectType] = useState("");
  const [action, setAction] = useState("");

  const events = useInfiniteQuery({
    queryKey: ["audit", from, to, objectType, action],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      ep.audit.events({
        since: startOf(from),
        until: endOf(to),
        object_type: objectType || undefined,
        action: action.trim() || undefined,
        cursor: pageParam,
        limit: 100,
      }),
    getNextPageParam: (last) => cursorFrom(last.next),
  });

  const rows = useMemo(() => events.data?.pages.flatMap((p) => p.results) ?? [], [events.data]);

  return (
    <>
      <PageHeader
        title="Audit log"
        description="An append-only record of material changes. Entries cannot be edited or removed."
      />
      <div className="mb-6 flex flex-wrap items-end gap-3">
        <Field label="From" className="w-44">
          {(p) => (
            <Input
              {...p}
              type="date"
              value={from}
              max={to}
              onChange={(e) => setFrom(e.target.value)}
            />
          )}
        </Field>
        <Field label="To" className="w-44">
          {(p) => (
            <Input
              {...p}
              type="date"
              value={to}
              min={from}
              onChange={(e) => setTo(e.target.value)}
            />
          )}
        </Field>
        <Field label="About" className="w-48">
          {(p) => (
            <Select {...p} value={objectType} onChange={(e) => setObjectType(e.target.value)}>
              {OBJECT_TYPES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Action contains" className="w-56">
          {(p) => (
            <Input
              {...p}
              value={action}
              onChange={(e) => setAction(e.target.value)}
              placeholder="for example review"
            />
          )}
        </Field>
      </div>

      {events.isLoading ? (
        <Skeleton className="h-96" />
      ) : events.isError ? (
        <QueryError error={events.error} onRetry={() => void events.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<History className="h-8 w-8" aria-hidden />}
          title="Nothing recorded in this window"
          description="Try a wider range of dates. Entries appear here as people and the system make changes."
        />
      ) : (
        <div className="rounded-lg border border-border bg-card p-6 shadow-card">
          <Timeline
            items={rows.map((e: AuditEvent) => ({
              id: e.id,
              title: e.action.replace(/[._]/g, " "),
              meta: `${formatDateTime(e.at)} · ${e.actor_role || "system"} · ${e.object_type} ${e.object_id.slice(0, 8)}`,
              system: !e.actor_id,
              detail:
                Object.keys(e.diff ?? {}).length > 0 ? (
                  <code className="mono block max-w-full overflow-x-auto whitespace-pre-wrap break-all text-caption text-subtle-foreground">
                    {JSON.stringify(e.diff)}
                  </code>
                ) : undefined,
            }))}
          />
          {events.hasNextPage ? (
            <div className="mt-6">
              <Button
                variant="outline"
                loading={events.isFetchingNextPage}
                onClick={() => void events.fetchNextPage()}
              >
                Load older entries
              </Button>
            </div>
          ) : null}
        </div>
      )}
    </>
  );
}
