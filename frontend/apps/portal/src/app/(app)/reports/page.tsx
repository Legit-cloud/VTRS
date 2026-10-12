"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  formatBytes,
  formatDateTime,
  formatNumber,
  type ExportJob,
  type StatusView,
} from "@vtrs/core";
import { Download, FileDown } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Skeleton } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/chip";
import { EmptyState, InlineAlert, QueryError } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { DataTable } from "@/components/vtrs/data-table";
import { PageHeader } from "@/components/vtrs/page-header";
import { ep } from "@/lib/api";
import { useContests, useElection } from "@/lib/election";
import { useStepUp } from "@/lib/step-up";

const KINDS = [
  ["RESULTS", "Results", "Votes by area, as a spreadsheet."],
  ["FLAGS", "Anomalies", "Every flag with its history."],
  ["AUDIT", "Audit log", "Who did what, in a time window."],
  [
    "EVIDENCE_PACK",
    "Evidence pack",
    "Result-sheet photos with a manifest of their SHA-256 hashes.",
  ],
] as const;

const JOB_STATUS: Record<string, StatusView> = {
  PENDING: { label: "Queued", tone: "ink", icon: "clock" },
  RUNNING: { label: "Preparing", tone: "blue", icon: "refresh-cw" },
  READY: { label: "Ready", tone: "teal", icon: "check-circle-2" },
  FAILED: { label: "Failed", tone: "red", icon: "alert-circle" },
  EXPIRED: { label: "Expired", tone: "ink", icon: "timer-off" },
};

const fail = (e: unknown, fallback: string) => (e instanceof ApiError ? e.detail : fallback);

export default function ReportsPage() {
  const { election } = useElection();
  const contests = useContests(election?.id);
  const queryClient = useQueryClient();
  const toast = useToast();
  const stepUp = useStepUp();

  const [kind, setKind] = useState<(typeof KINDS)[number][0]>("RESULTS");
  const [format, setFormat] = useState("CSV");
  const [contestId, setContestId] = useState("");
  const [level, setLevel] = useState("lga");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [error, setError] = useState<string | null>(null);

  const jobs = useQuery({
    queryKey: ["exports"],
    queryFn: async () => (await ep.exports.list({ limit: 50 })).results,
    // Keep checking while anything is still being built.
    refetchInterval: (query) =>
      (query.state.data ?? []).some((j) => j.status === "PENDING" || j.status === "RUNNING")
        ? 3000
        : false,
  });

  const request = useMutation({
    mutationFn: () =>
      stepUp(() =>
        ep.exports.request({
          kind,
          format: (kind === "EVIDENCE_PACK" ? "ZIP" : format) as never,
          election_id: election?.id,
          contest_id: kind === "RESULTS" ? contestId || contests.data?.[0]?.id : undefined,
          level: kind === "RESULTS" ? (level as never) : undefined,
          since: since ? `${since}T00:00:00+01:00` : undefined,
          until: until ? `${until}T23:59:59+01:00` : undefined,
        }),
      ),
    onSuccess: () => {
      toast("Export requested");
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ["exports"] });
    },
    onError: (e) => setError(fail(e, "Could not request the export.")),
  });

  const download = useMutation({
    mutationFn: (id: string) => ep.exports.downloadUrl(id),
    onSuccess: (data) => window.open(data.url, "_blank", "noopener,noreferrer"),
    onError: (e) => toast(fail(e, "Could not start the download.")),
  });

  const formats = kind === "EVIDENCE_PACK" ? ["ZIP"] : ["CSV", "XLSX"];

  return (
    <>
      <PageHeader
        title="Reports"
        description="Export results, anomalies, the audit log or evidence. Every export is recorded and links expire after a short time."
      />

      <Card className="mb-8">
        <CardHeader title="New export" />
        <form
          className="grid grid-cols-1 gap-4 p-5 pt-2 md:grid-cols-2 xl:grid-cols-3"
          onSubmit={(e) => {
            e.preventDefault();
            request.mutate();
          }}
        >
          {error ? (
            <div className="md:col-span-2 xl:col-span-3">
              <InlineAlert tone="danger" title="Not requested">
                {error}
              </InlineAlert>
            </div>
          ) : null}
          <Field label="What to export" hint={KINDS.find((k) => k[0] === kind)?.[2]}>
            {(p) => (
              <Select
                {...p}
                value={kind}
                onChange={(e) => {
                  const next = e.target.value as typeof kind;
                  setKind(next);
                  setFormat(next === "EVIDENCE_PACK" ? "ZIP" : "CSV");
                }}
              >
                {KINDS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Format">
            {(p) => (
              <Select
                {...p}
                value={format}
                onChange={(e) => setFormat(e.target.value)}
                disabled={formats.length === 1}
              >
                {formats.map((f) => (
                  <option key={f}>{f}</option>
                ))}
              </Select>
            )}
          </Field>
          {kind === "RESULTS" ? (
            <>
              <Field label="Contest">
                {(p) => (
                  <Select {...p} value={contestId} onChange={(e) => setContestId(e.target.value)}>
                    {(contests.data ?? []).map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.title}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label="Detail">
                {(p) => (
                  <Select {...p} value={level} onChange={(e) => setLevel(e.target.value)}>
                    <option value="lga">By LGA</option>
                    <option value="ward">By ward</option>
                    <option value="pu">By polling unit</option>
                  </Select>
                )}
              </Field>
            </>
          ) : null}
          {kind === "AUDIT" || kind === "FLAGS" ? (
            <>
              <Field label="From">
                {(p) => (
                  <Input
                    {...p}
                    type="date"
                    value={since}
                    onChange={(e) => setSince(e.target.value)}
                  />
                )}
              </Field>
              <Field label="To">
                {(p) => (
                  <Input
                    {...p}
                    type="date"
                    value={until}
                    onChange={(e) => setUntil(e.target.value)}
                  />
                )}
              </Field>
            </>
          ) : null}
          <div className="flex items-end md:col-span-2 xl:col-span-3">
            <Button
              type="submit"
              loading={request.isPending}
              leading={<FileDown className="h-4 w-4" aria-hidden />}
              disabled={!election}
            >
              {kind === "EVIDENCE_PACK" ? "Request evidence pack" : "Request export"}
            </Button>
          </div>
        </form>
      </Card>

      <h2 className="mb-3 text-h2">Your exports</h2>
      {jobs.isLoading ? (
        <Skeleton className="h-48" />
      ) : jobs.isError ? (
        <QueryError error={jobs.error} onRetry={() => void jobs.refetch()} />
      ) : (
        <DataTable<ExportJob>
          caption="Exports"
          rows={jobs.data ?? []}
          rowKey={(j) => j.id}
          columns={[
            {
              key: "kind",
              header: "Export",
              cell: (j) => (
                <span>
                  <span className="font-semibold">
                    {KINDS.find((k) => k[0] === j.kind)?.[1] ?? j.kind}
                  </span>
                  <span className="ml-2 text-caption text-subtle-foreground">{j.format}</span>
                </span>
              ),
            },
            {
              key: "status",
              header: "Status",
              cell: (j) => <StatusChip status={JOB_STATUS[j.status] ?? JOB_STATUS.PENDING!} />,
            },
            {
              key: "size",
              header: "Size",
              numeric: true,
              cell: (j) =>
                j.status === "READY"
                  ? `${formatBytes(j.size)}${j.row_count != null ? ` · ${formatNumber(j.row_count)} rows` : ""}`
                  : "–",
              hideOnNarrow: true,
            },
            {
              key: "at",
              header: "Requested",
              cell: (j) => formatDateTime(j.requested_at),
              sortValue: (j) => j.requested_at,
            },
            {
              key: "get",
              header: "",
              cell: (j) =>
                j.status === "READY" ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    leading={<Download className="h-4 w-4" aria-hidden />}
                    loading={download.isPending && download.variables === j.id}
                    onClick={() => download.mutate(j.id)}
                  >
                    Download
                  </Button>
                ) : j.status === "FAILED" ? (
                  <span className="text-caption text-signal-red-text">
                    {j.error || "The export failed."}
                  </span>
                ) : null,
            },
          ]}
          empty={
            <EmptyState
              icon={<FileDown className="h-8 w-8" aria-hidden />}
              title="No exports yet"
              description="Request one above. It is built in the background and appears here when it is ready."
            />
          }
          initialSort={{ key: "at", dir: "desc" }}
        />
      )}
    </>
  );
}
