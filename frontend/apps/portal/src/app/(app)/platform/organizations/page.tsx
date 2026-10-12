"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { cursorFrom, formatDate, formatNumber, type PlatformOrg } from "@vtrs/core";
import { Building2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/card";
import { EmptyState, QueryError } from "@/components/ui/feedback";
import { Field, Select } from "@/components/ui/field";
import { DataTable } from "@/components/vtrs/data-table";
import { OrgPanel } from "@/components/vtrs/org-panel";
import { PageHeader } from "@/components/vtrs/page-header";
import { ep } from "@/lib/api";
import { ORG_STATUS, orgStatus } from "@/lib/platform";

export default function OrganizationsPage() {
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  const list = useInfiniteQuery({
    queryKey: ["platform", "orgs", status],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      ep.platform.organizations({ status: status || undefined, cursor: pageParam, limit: 100 }),
    getNextPageParam: (last) => cursorFrom(last.next),
  });
  const rows = useMemo(() => list.data?.pages.flatMap((p) => p.results) ?? [], [list.data]);

  return (
    <>
      <PageHeader title="Organisations" description="Who is on the platform, and in what state." />
      <div className="mb-4">
        <Field label="Status" className="w-56">
          {(p) => (
            <Select {...p} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All</option>
              {Object.entries(ORG_STATUS).map(([value, view]) => (
                <option key={value} value={value}>
                  {view.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      {list.isError ? (
        <QueryError error={list.error} onRetry={() => void list.refetch()} />
      ) : list.isLoading ? (
        <Skeleton className="h-72" />
      ) : (
        <DataTable<PlatformOrg>
          caption="Organisations"
          dense
          rows={rows}
          rowKey={(o) => o.id}
          selectedKey={open}
          onRowClick={(o) => setOpen(o.id)}
          initialSort={{ key: "created", dir: "desc" }}
          columns={[
            {
              key: "name",
              header: "Organisation",
              cell: (o) => <span className="font-semibold">{o.name}</span>,
              sortValue: (o) => o.name,
            },
            {
              key: "status",
              header: "Status",
              cell: (o) => <StatusChip status={orgStatus(o.status)} />,
              sortValue: (o) => o.status,
            },
            {
              key: "elections",
              header: "Elections",
              numeric: true,
              cell: (o) => formatNumber(o.election_count),
              sortValue: (o) => o.election_count,
            },
            {
              key: "agents",
              header: "Agents",
              numeric: true,
              cell: (o) => formatNumber(o.agents),
              sortValue: (o) => o.agents,
            },
            {
              key: "people",
              header: "People",
              numeric: true,
              cell: (o) => formatNumber(o.people),
              sortValue: (o) => o.people,
              hideOnNarrow: true,
            },
            {
              key: "created",
              header: "Registered",
              cell: (o) => formatDate(o.created_at),
              sortValue: (o) => o.created_at,
              hideOnNarrow: true,
            },
          ]}
          empty={
            <EmptyState
              icon={<Building2 className="h-8 w-8" aria-hidden />}
              title="No organisations match"
              description="Parties appear here when they register."
            />
          }
          footer={
            list.hasNextPage ? (
              <Button
                variant="outline"
                size="sm"
                loading={list.isFetchingNextPage}
                onClick={() => void list.fetchNextPage()}
              >
                Load more
              </Button>
            ) : undefined
          }
        />
      )}
      <OrgPanel organizationId={open} onClose={() => setOpen(null)} />
    </>
  );
}
