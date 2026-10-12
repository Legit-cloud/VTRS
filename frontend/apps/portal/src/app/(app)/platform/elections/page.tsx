"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import {
  cursorFrom,
  electionStatus,
  formatDate,
  formatDateTime,
  type PlatformElection,
} from "@vtrs/core";
import { Vote } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/card";
import { EmptyState, QueryError } from "@/components/ui/feedback";
import { Field, Select } from "@/components/ui/field";
import { DataTable } from "@/components/vtrs/data-table";
import { PageHeader } from "@/components/vtrs/page-header";
import { ep } from "@/lib/api";

const STATUSES = ["DRAFT", "CONFIGURED", "LOCKED", "LIVE", "CLOSED", "RECONCILED"];

export default function PlatformElections() {
  const [status, setStatus] = useState("");
  const list = useInfiniteQuery({
    queryKey: ["platform", "elections", status],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      ep.platform.elections({ status: status || undefined, cursor: pageParam, limit: 100 }),
    getNextPageParam: (last) => cursorFrom(last.next),
  });
  const rows = useMemo(() => list.data?.pages.flatMap((p) => p.results) ?? [], [list.data]);

  return (
    <>
      <PageHeader
        title="Elections"
        description="Every election on the platform, who owns it, and whether its configuration is locked."
      />
      <div className="mb-4">
        <Field label="Status" className="w-56">
          {(p) => (
            <Select {...p} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {electionStatus(s).label}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      {list.isError ? (
        <QueryError error={list.error} onRetry={() => void list.refetch()} />
      ) : list.isLoading ? (
        <Skeleton className="h-64" />
      ) : (
        <DataTable<PlatformElection>
          caption="Elections across all organisations"
          dense
          rows={rows}
          rowKey={(e) => e.id}
          columns={[
            {
              key: "name",
              header: "Election",
              cell: (e) => <span className="font-semibold">{e.name}</span>,
              sortValue: (e) => e.name,
            },
            {
              key: "org",
              header: "Organisation",
              cell: (e) => e.organization_name,
              sortValue: (e) => e.organization_name,
            },
            {
              key: "status",
              header: "Status",
              cell: (e) => <StatusChip status={electionStatus(e.status)} />,
              sortValue: (e) => e.status,
            },
            {
              key: "date",
              header: "Election date",
              cell: (e) => formatDate(e.election_date),
              sortValue: (e) => e.election_date,
            },
            {
              key: "locked",
              header: "Locked",
              cell: (e) => (e.locked_at ? formatDateTime(e.locked_at) : "Not yet"),
              hideOnNarrow: true,
            },
          ]}
          initialSort={{ key: "date", dir: "desc" }}
          empty={
            <EmptyState
              icon={<Vote className="h-8 w-8" aria-hidden />}
              title="No elections yet"
              description="Elections appear here when parties create them."
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
    </>
  );
}
