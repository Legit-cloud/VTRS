"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { cursorFrom, formatDateTime } from "@vtrs/core";
import { History } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/card";
import { EmptyState, QueryError } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/field";
import { PageHeader } from "@/components/vtrs/page-header";
import { Timeline } from "@/components/vtrs/timeline";
import { ep } from "@/lib/api";

const today = () => new Date(Date.now() + 3600_000).toISOString().slice(0, 10);
const startOf = (day: string) => new Date(`${day}T00:00:00+01:00`).toISOString();
const endOf = (day: string) => new Date(`${day}T23:59:59.999+01:00`).toISOString();

export default function PlatformAudit() {
  const [from, setFrom] = useState(today());
  const [to, setTo] = useState(today());
  const [organization, setOrganization] = useState("");
  const [action, setAction] = useState("");

  const orgs = useQuery({
    queryKey: ["platform", "orgs", "picker"],
    queryFn: async () => (await ep.platform.organizations({ limit: 200 })).results,
    staleTime: 60_000,
  });

  const events = useInfiniteQuery({
    queryKey: ["platform", "audit", from, to, organization, action],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      ep.platform.audit({
        since: startOf(from),
        until: endOf(to),
        organization_id: organization || undefined,
        action: action.trim() || undefined,
        cursor: pageParam,
        limit: 100,
      }),
    getNextPageParam: (last) => cursorFrom(last.next),
  });
  const rows = useMemo(() => events.data?.pages.flatMap((p) => p.results) ?? [], [events.data]);
  const orgName = (id: string | null) => orgs.data?.find((o) => o.id === id)?.name ?? "Platform";

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Everything that happened across the platform. Entries cannot be edited or removed."
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
        <Field label="Organisation" className="w-56">
          {(p) => (
            <Select {...p} value={organization} onChange={(e) => setOrganization(e.target.value)}>
              <option value="">All</option>
              {(orgs.data ?? []).map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
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
              placeholder="for example approved"
            />
          )}
        </Field>
      </div>

      {events.isError ? (
        <QueryError error={events.error} onRetry={() => void events.refetch()} />
      ) : events.isLoading ? (
        <Skeleton className="h-96" />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<History className="h-8 w-8" aria-hidden />}
          title="Nothing recorded in this window"
          description="Try a wider range of dates or another organisation."
        />
      ) : (
        <div className="rounded-lg border border-border bg-card p-6 shadow-card">
          <Timeline
            items={rows.map((e) => ({
              id: e.id,
              title: e.action.replace(/[._]/g, " "),
              meta: `${formatDateTime(e.at)} · ${orgName(e.organization_id)} · ${e.actor_role || "system"}`,
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
