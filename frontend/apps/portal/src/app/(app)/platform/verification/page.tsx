"use client";

import { useQuery } from "@tanstack/react-query";
import { formatDateTime, type PlatformOrg } from "@vtrs/core";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Skeleton } from "@/components/ui/card";
import { EmptyState, QueryError } from "@/components/ui/feedback";
import { DataTable } from "@/components/vtrs/data-table";
import { OrgPanel } from "@/components/vtrs/org-panel";
import { PageHeader } from "@/components/vtrs/page-header";
import { ep } from "@/lib/api";

export default function VerificationQueue() {
  const [open, setOpen] = useState<string | null>(null);
  const queue = useQuery({
    queryKey: ["platform", "verification"],
    queryFn: async () => (await ep.platform.verificationQueue({ limit: 100 })).results,
    refetchInterval: 30_000,
  });

  return (
    <>
      <PageHeader
        title="Verification queue"
        description="Organisations whose registrant has confirmed their code and who are waiting for you. Oldest first."
      />
      {queue.isError ? (
        <QueryError error={queue.error} onRetry={() => void queue.refetch()} />
      ) : queue.isLoading ? (
        <Skeleton className="h-64" />
      ) : (
        <DataTable<PlatformOrg>
          caption="Organisations waiting for approval"
          rows={queue.data ?? []}
          rowKey={(o) => o.id}
          onRowClick={(o) => setOpen(o.id)}
          selectedKey={open}
          columns={[
            {
              key: "name",
              header: "Organisation",
              cell: (o) => <span className="font-semibold">{o.name}</span>,
            },
            {
              key: "legal",
              header: "Legal name",
              cell: (o) => o.legal_name || "–",
              hideOnNarrow: true,
            },
            {
              key: "verified",
              header: "Code confirmed",
              cell: (o) => formatDateTime(o.verified_at),
            },
            {
              key: "created",
              header: "Registered",
              cell: (o) => formatDateTime(o.created_at),
              hideOnNarrow: true,
            },
          ]}
          empty={
            <EmptyState
              icon={<ShieldCheck className="h-8 w-8" aria-hidden />}
              title="Nobody is waiting"
              description="New registrations appear here once the registrant confirms the code we send them."
            />
          }
        />
      )}
      <OrgPanel organizationId={open} onClose={() => setOpen(null)} />
    </>
  );
}
