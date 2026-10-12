"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { ApiError, reviewState, type AreaResult } from "@vtrs/core";
import { FileSearch, PackageOpen } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/chip";
import { EmptyState, InlineAlert, QueryError } from "@/components/ui/feedback";
import { Field, Select } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { EvidenceCard } from "@/components/vtrs/evidence-card";
import { PageHeader } from "@/components/vtrs/page-header";
import { ep } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useContests, useElection } from "@/lib/election";
import { useElectionLgas } from "@/lib/geo-names";
import { useStepUp } from "@/lib/step-up";

/**
 * There is no flat list of photos on the API: evidence belongs to a result version. So this page
 * works the way a reviewer does: pick a ward, see its polling units, open one to see its photos.
 */
export default function EvidencePage() {
  const { election } = useElection();
  const { can } = useAuth();
  const contests = useContests(election?.id);
  const toast = useToast();
  const stepUp = useStepUp();
  const [lgaId, setLgaId] = useState("");
  const [wardId, setWardId] = useState("");
  const [contestId, setContestId] = useState("");
  const [openUnit, setOpenUnit] = useState<string | null>(null);

  const activeContest = contestId || contests.data?.[0]?.id || "";

  const { lgas } = useElectionLgas();
  const wards = useQuery({
    queryKey: ["geo", "wards", lgaId],
    enabled: !!lgaId,
    queryFn: async () => (await ep.geography.wards({ lga: lgaId, limit: 200 })).results,
    staleTime: 10 * 60_000,
  });
  const units = useQuery({
    queryKey: ["results", activeContest, "pu", wardId, "evidence"],
    enabled: !!activeContest && !!wardId,
    queryFn: () => ep.contests.results(activeContest, { level: "pu", parent_id: wardId }),
  });

  const pack = useMutation({
    mutationFn: () =>
      stepUp(() =>
        ep.exports.request({
          kind: "EVIDENCE_PACK",
          format: "ZIP",
          election_id: election!.id,
          ward_id: wardId,
        }),
      ),
    onSuccess: () => toast("Evidence pack requested. It will appear under Reports."),
    onError: (e) => toast(e instanceof ApiError ? e.detail : "Could not request the pack."),
  });

  if (!election) {
    return (
      <>
        <PageHeader title="Evidence" />
        <EmptyState
          icon={<FileSearch className="h-8 w-8" aria-hidden />}
          title="No election yet"
          description="Result-sheet photos appear here once agents start sending results."
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Evidence"
        description="Result-sheet photos, each with its SHA-256 hash. Opening a photo is recorded in its chain of custody."
        actions={
          can("evidence.export") && wardId ? (
            <Button
              variant="secondary"
              leading={<PackageOpen className="h-4 w-4" aria-hidden />}
              loading={pack.isPending}
              onClick={() => pack.mutate()}
            >
              Download evidence pack
            </Button>
          ) : undefined
        }
      />

      <div className="mb-6 flex flex-wrap items-end gap-3">
        {contests.data && contests.data.length > 1 ? (
          <Field label="Contest" className="w-56">
            {(p) => (
              <Select {...p} value={activeContest} onChange={(e) => setContestId(e.target.value)}>
                {contests.data!.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        ) : null}
        <Field label="LGA" className="w-56">
          {(p) => (
            <Select
              {...p}
              value={lgaId}
              onChange={(e) => {
                setLgaId(e.target.value);
                setWardId("");
                setOpenUnit(null);
              }}
            >
              <option value="">Choose an LGA…</option>
              {lgas.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Ward" className="w-56">
          {(p) => (
            <Select
              {...p}
              value={wardId}
              disabled={!lgaId}
              onChange={(e) => {
                setWardId(e.target.value);
                setOpenUnit(null);
              }}
            >
              <option value="">Choose a ward…</option>
              {(wards.data ?? []).map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>

      {!wardId ? (
        <EmptyState
          icon={<FileSearch className="h-8 w-8" aria-hidden />}
          title="Choose a ward"
          description="Pick an LGA and a ward to see its polling units and their result-sheet photos."
        />
      ) : units.isLoading ? (
        <Skeleton className="h-64" />
      ) : units.isError ? (
        <QueryError error={units.error} onRetry={() => void units.refetch()} />
      ) : (units.data?.rows ?? []).length === 0 ? (
        <EmptyState
          icon={<FileSearch className="h-8 w-8" aria-hidden />}
          title="No polling units here"
          description="This ward has no polling units in the selected contest."
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {units.data!.rows.map((row: AreaResult) => (
            <li key={row.area_id} className="rounded-lg border border-border bg-card shadow-card">
              <button
                type="button"
                className="flex w-full flex-wrap items-center gap-3 p-4 text-left"
                aria-expanded={openUnit === row.area_id}
                onClick={() => setOpenUnit(openUnit === row.area_id ? null : row.area_id)}
              >
                <span className="font-semibold">{row.area_name}</span>
                <span className="mono text-caption text-subtle-foreground">{row.area_code}</span>
                <span className="ml-auto">
                  {row.status && row.status !== "NOT_REPORTED" ? (
                    <StatusChip status={reviewState(row.status)} />
                  ) : (
                    <span className="text-body-sm text-subtle-foreground">Not reported</span>
                  )}
                </span>
              </button>
              {openUnit === row.area_id ? (
                <UnitEvidence
                  contestId={activeContest}
                  unitId={row.area_id}
                  canView={can("evidence.view")}
                />
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function UnitEvidence({
  contestId,
  unitId,
  canView,
}: {
  contestId: string;
  unitId: string;
  canView: boolean;
}) {
  const history = useQuery({
    queryKey: ["results", "history", contestId, unitId],
    queryFn: () => ep.contests.history(contestId, unitId),
  });
  if (history.isLoading) return <Skeleton className="m-4 h-24" />;
  if (history.isError) {
    return (
      <div className="p-4">
        <QueryError error={history.error} onRetry={() => void history.refetch()} />
      </div>
    );
  }
  const head = history.data?.versions.find((v) => v.is_head) ?? history.data?.versions[0];
  const evidence = head?.evidence ?? [];
  return (
    <div className="flex flex-col gap-3 border-t border-border p-4">
      {evidence.length === 0 ? (
        <InlineAlert tone="warning" title="No photo received">
          This result has no result-sheet photo yet. A flag is raised if none arrives within 30
          minutes.
        </InlineAlert>
      ) : (
        evidence.map((e) => (
          <EvidenceCard
            key={e.evidence_id}
            item={e}
            canView={canView}
            place={history.data!.polling_unit_code}
          />
        ))
      )}
    </div>
  );
}
